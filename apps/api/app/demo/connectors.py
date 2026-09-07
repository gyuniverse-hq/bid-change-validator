"""The seams where data comes from — and where the database will plug in.

The team's schema is not delivered yet, so nothing here reads the ORM. Instead
each source of data is a `Protocol` with a working implementation that uses what
we already have: the live 나라장터 API, the collected master-code CSVs, and demo
company profiles on disk.

That is the point of writing them as protocols rather than as functions. When the
tables land, a `SqlAlchemy*` implementation satisfies the same protocol and the
pipeline does not change. Until then the demo runs end to end on real notice data
with a fictional company, which is the part worth showing now.

    NoticeSource     공고 원본        → G2BNoticeSource / FixtureNoticeSource
    ProfileStore     회사 프로필      → FileProfileStore        ← DB가 대체할 자리
    IndustryCatalog  업종·근거법규    → CsvIndustryCatalog      ← DB가 대체할 자리
    PriceBoard       계약 가격 표시   → NoticePriceBoard
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..ai.notice_requirements import NoticePriceInfo, extract_notice_facts
from ..ai.profile import CompanyProfileSnapshot


REPO_ROOT = Path(__file__).resolve().parents[4]
DEMO_PROFILE_DIR = REPO_ROOT / "data" / "demo" / "profiles"
INDUSTRY_CSV = REPO_ROOT / "data" / "master" / "industry_codes.csv"
FIXTURE_DIR = REPO_ROOT / "data" / "demo" / "notices"

# Raise the CSV field cap: `raw_json` holds a whole API record per row.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


# ── notices ──────────────────────────────────────────────────────────────
@runtime_checkable
class NoticeSource(Protocol):
    """Where one notice record comes from, keyed by its 공고번호."""

    def fetch(self, notice_no: str) -> dict[str, Any] | None: ...


class G2BNoticeSource:
    """The live 입찰공고정보서비스.

    Reuses Backend's `G2BClient` unchanged — it is a plain HTTP client with no
    database dependency, so there is nothing to duplicate here.
    """

    def __init__(
        self,
        *,
        service_key: str,
        base_url: str,
        business_types: list[str] | None = None,
        timeout_seconds: float = 30.0,
        cache_dir: Path | None = None,
    ) -> None:
        from ..schemas import BusinessType
        from ..services.g2b import G2BClient

        self._client = G2BClient(
            service_key=service_key, base_url=base_url, timeout_seconds=timeout_seconds
        )
        # A notice number belongs to exactly one business type, but which one is
        # not knowable in advance, so the endpoints are tried in turn.
        self._business_types = [
            BusinessType(name)
            for name in (business_types or ["SERVICE", "GOODS", "CONSTRUCTION", "FOREIGN"])
        ]
        self._cache_dir = cache_dir

    def fetch(self, notice_no: str) -> dict[str, Any] | None:
        from ..schemas import NoticeInquiryType
        from ..services.g2b import G2BApiError

        for business_type in self._business_types:
            try:
                page = self._client.fetch_page(
                    business_type=business_type,
                    inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
                    page_number=1,
                    page_size=10,
                    bid_notice_no=notice_no,
                )
            except G2BApiError:
                continue
            if page.items:
                item = page.items[0]
                self._cache(notice_no, item)
                return item
        return None

    def _cache(self, notice_no: str, item: dict[str, Any]) -> None:
        """Keep the raw record so a demo can be replayed without the network."""
        if self._cache_dir is None:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / f"{notice_no}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class FixtureNoticeSource:
    """Notice records saved to disk, so the demo runs with no network or key."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or FIXTURE_DIR

    def fetch(self, notice_no: str) -> dict[str, Any] | None:
        path = self.directory / f"{notice_no}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Accept either a bare record or a saved API envelope.
        if "response" in payload:
            items = payload["response"].get("body", {}).get("items", [])
            if isinstance(items, dict):
                items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]
            return items[0] if items else None
        return payload

    def available(self) -> list[str]:
        if not self.directory.exists():
            return []
        return sorted(path.stem for path in self.directory.glob("*.json"))


class ChainedNoticeSource:
    """Try each source in order — fixtures first, then the network."""

    def __init__(self, *sources: NoticeSource) -> None:
        self._sources = sources

    def fetch(self, notice_no: str) -> dict[str, Any] | None:
        for source in self._sources:
            item = source.fetch(notice_no)
            if item is not None:
                return item
        return None


# ── company profiles ─────────────────────────────────────────────────────
@runtime_checkable
class ProfileStore(Protocol):
    """Where a company profile comes from. The database will implement this."""

    def list_ids(self) -> list[str]: ...

    def get(self, profile_id: str) -> CompanyProfileSnapshot | None: ...


class FileProfileStore:
    """Fictional company profiles kept as JSON.

    Every profile carries `_demo` and a scenario note, because a screenshot of a
    verdict against a made-up company must never be mistaken for a real one.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or DEMO_PROFILE_DIR

    def _paths(self) -> dict[str, Path]:
        if not self.directory.exists():
            return {}
        return {path.stem: path for path in sorted(self.directory.glob("*.json"))}

    def list_ids(self) -> list[str]:
        return list(self._paths())

    def raw(self, profile_id: str) -> dict[str, Any] | None:
        path = self._paths().get(profile_id)
        if path is None:
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get(self, profile_id: str) -> CompanyProfileSnapshot | None:
        payload = self.raw(profile_id)
        if payload is None:
            return None
        return CompanyProfileSnapshot.model_validate(payload)

    def scenario(self, profile_id: str) -> str | None:
        payload = self.raw(profile_id) or {}
        return payload.get("_시나리오") or payload.get("_scenario")


# ── industry codes and the statute behind them ───────────────────────────
@dataclass(frozen=True)
class IndustryEntry:
    code: str
    name: str
    active: bool
    classification: str | None = None
    base_law: str | None = None
    base_law_article: str | None = None

    @property
    def legal_basis(self) -> str | None:
        if not self.base_law:
            return None
        if self.base_law_article:
            return f"{self.base_law} {self.base_law_article}"
        return self.base_law


@runtime_checkable
class IndustryCatalog(Protocol):
    def by_code(self, code: str) -> IndustryEntry | None: ...

    def by_name(self, name: str) -> IndustryEntry | None: ...


class CsvIndustryCatalog:
    """업종 및 근거법규 서비스, as already collected into `data/master`.

    The API's own record is kept in the `raw_json` column, which is where the
    statute behind an industry code lives. Showing "정보통신공사업" next to
    "정보통신공사업법 제14조" is the difference between a code and a reason.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or INDUSTRY_CSV
        self._by_code: dict[str, IndustryEntry] = {}
        self._by_name: dict[str, IndustryEntry] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                raw: dict[str, Any] = {}
                if row.get("raw_json"):
                    try:
                        raw = json.loads(row["raw_json"])
                    except json.JSONDecodeError:
                        raw = {}
                entry = IndustryEntry(
                    code=(row.get("code") or "").strip(),
                    name=(row.get("name") or "").strip(),
                    active=(row.get("active") or "").strip().upper() != "N",
                    classification=raw.get("indstrytyClsfcNm") or None,
                    base_law=raw.get("baseLawordNm") or None,
                    base_law_article=raw.get("baseLawordArtclClauseNm") or None,
                )
                if entry.code:
                    self._by_code.setdefault(entry.code, entry)
                if entry.name:
                    self._by_name.setdefault(entry.name, entry)

    def by_code(self, code: str) -> IndustryEntry | None:
        self._load()
        return self._by_code.get((code or "").strip())

    def by_name(self, name: str) -> IndustryEntry | None:
        self._load()
        return self._by_name.get((name or "").strip())

    def describe(self, code_or_name: str) -> IndustryEntry | None:
        return self.by_code(code_or_name) or self.by_name(code_or_name)

    def __len__(self) -> int:
        self._load()
        return len(self._by_code)


# ── contract price, for display ──────────────────────────────────────────
@runtime_checkable
class PriceBoard(Protocol):
    def price_of(self, item: dict[str, Any]) -> NoticePriceInfo: ...


class NoticePriceBoard:
    """Contract price taken from the notice record itself.

    Display only, and kept behind a protocol on purpose: 조달청 가격정보현황서비스 can
    replace this without the pipeline noticing, and the figures still must not
    reach a qualification verdict either way.
    """

    def price_of(self, item: dict[str, Any]) -> NoticePriceInfo:
        return extract_notice_facts(item).price
