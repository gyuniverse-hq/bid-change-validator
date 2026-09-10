"""Fetching the notice document itself, without the database.

Measured over 300 live notices, the list API carries a judgeable participation
requirement for 0.7% of them. Half say "there is an industry restriction" without
saying which industry. The actual conditions are in the attachment, so a review
that never opens the attachment cannot judge anything.

Backend already downloads and extracts attachments, but that path writes
`NoticeDocument` rows and the schema is not delivered yet. The useful half of it
is not DB-coupled though: `extract_document(source, filename, content_type)`
takes a file handle and returns text plus source blocks. So this module does the
two steps around it — fetch the bytes, hand back the blocks — and the database
seam stays exactly where it was.

The blocks that come back carry page and section locators, which is why they are
passed through to chunking as-is rather than being flattened to text. Evidence
that cites "p.14" is only possible because that locator survives.

One format needs handling that Backend's extractor does not do yet: 나라장터 and
법제처 both serve HWPML — an XML document named `.hwp` — which the extractor
rejects as "not an OLE2 structured storage file". Until that lands in
`app.services.document_extraction`, the reader below covers it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from xml.etree import ElementTree

import requests

from ..qualification.extraction.notice_requirements import extract_notice_facts


REPO_ROOT = Path(__file__).resolve().parents[5]
DOCUMENT_CACHE_DIR = REPO_ROOT / "data" / "demo" / "notice-documents"

# Attachments are usually a 공고문 plus forms, drawings and price sheets. Only the
# first few carry participation conditions, and each one costs a download.
DEFAULT_MAX_DOCUMENTS = 4
DOWNLOAD_TIMEOUT_SECONDS = 60.0
MAX_DOCUMENT_BYTES = 40 * 1024 * 1024

_HWPML_HINT = b"HWPML"
_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)


@dataclass
class FetchedDocument:
    """One downloaded attachment and whatever could be read out of it."""

    url: str
    filename: str
    content_type: str | None = None
    size_bytes: int = 0
    sha256: str | None = None
    extractor: str | None = None
    text: str = ""
    blocks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def extracted(self) -> bool:
        return bool(self.text.strip())


@runtime_checkable
class NoticeDocumentSource(Protocol):
    """Where a notice's attachments come from. The database will implement this."""

    def fetch(self, item: dict[str, Any]) -> list[FetchedDocument]: ...


# ── HWPML, the format the extension does not admit to ────────────────────
def is_hwpml(head: bytes) -> bool:
    return head.lstrip().startswith(b"<?xml") and _HWPML_HINT in head


def _paragraph_own_text(element: Any) -> str:
    """Text belonging to this paragraph, excluding paragraphs nested in tables.

    A table sits inside a paragraph and its cells hold their own paragraphs, so
    collecting every descendant would emit cell text twice.
    """
    parts: list[str] = []
    for child in element:
        if child.tag == "P":
            continue
        if child.tag == "CHAR":
            if child.text:
                parts.append(child.text)
        else:
            parts.append(_paragraph_own_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def extract_hwpml(payload: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Read HWPML into the same (text, blocks) shape Backend's extractor returns."""
    root = ElementTree.fromstring(payload.decode("utf-8", errors="replace"))
    lines = [_paragraph_own_text(node) for node in root.iter("P")]

    blocks: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        blocks.append(
            {
                "block_index": len(blocks),
                "page": None,
                "section_index": None,
                "paragraph_index": index,
                "text": line.strip(),
            }
        )
    return "\n".join(line for line in lines if line.strip()), blocks


def _filename_from_headers(headers: Any, fallback: str) -> str:
    disposition = headers.get("Content-Disposition") or ""
    match = _FILENAME_RE.search(disposition)
    if not match:
        return fallback
    from urllib.parse import unquote

    return unquote(match.group(1)).strip() or fallback


def _document_targets(item: dict[str, Any]) -> list[tuple[str, str]]:
    """(url, filename) pairs, using the notice's own attachment names.

    `ntceSpecFileNm{n}` pairs with `ntceSpecDocUrl{n}`, which is more reliable than
    guessing an extension from a download URL that has none.
    """
    targets: list[tuple[str, str]] = []
    standard_url = (item.get("stdNtceDocUrl") or "").strip()
    if standard_url:
        targets.append((standard_url, "표준공고문"))

    for order in range(1, 11):
        url = (item.get(f"ntceSpecDocUrl{order}") or "").strip()
        if not url:
            continue
        name = (item.get(f"ntceSpecFileNm{order}") or "").strip() or f"attachment_{order}"
        targets.append((url, name))
    return targets


class G2BDocumentSource:
    """Download a notice's attachments and extract their text.

    Downloads are cached on disk so a demo can be replayed, and re-run without
    hitting 나라장터 again for a document that has not changed.
    """

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        max_documents: int = DEFAULT_MAX_DOCUMENTS,
        timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self.cache_dir = cache_dir or DOCUMENT_CACHE_DIR
        self.max_documents = max_documents
        self.timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def fetch(self, item: dict[str, Any]) -> list[FetchedDocument]:
        notice_no = extract_notice_facts(item).notice_no or "unknown"
        documents: list[FetchedDocument] = []
        # 표준공고문 and the first attachment are routinely the same file under two
        # URLs. Extracting it twice doubles the chunks and every downstream cost.
        seen_digests: set[str] = set()

        for url, filename in _document_targets(item)[: self.max_documents]:
            document = self._fetch_one(notice_no, url, filename)
            if document.sha256 and document.sha256 in seen_digests:
                continue
            if document.sha256:
                seen_digests.add(document.sha256)
            documents.append(document)
        return documents

    def _cache_path(self, notice_no: str, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / notice_no / f"{digest}.bin"

    def _fetch_one(self, notice_no: str, url: str, filename: str) -> FetchedDocument:
        document = FetchedDocument(url=url, filename=filename)
        cache_path = self._cache_path(notice_no, url)
        meta_path = cache_path.with_suffix(".json")

        payload: bytes | None = None
        if cache_path.exists():
            payload = cache_path.read_bytes()
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                document.filename = meta.get("filename") or filename
                document.content_type = meta.get("content_type")

        if payload is None:
            try:
                response = self._session.get(
                    url, timeout=self.timeout_seconds, stream=True
                )
                response.raise_for_status()
                payload = response.content
            except requests.RequestException as error:
                document.error = f"다운로드 실패: {type(error).__name__}"
                return document

            if len(payload) > MAX_DOCUMENT_BYTES:
                document.error = f"파일이 너무 큽니다 ({len(payload):,} bytes)"
                return document

            document.content_type = response.headers.get("Content-Type")
            document.filename = _filename_from_headers(response.headers, filename)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(payload)
            meta_path.write_text(
                json.dumps(
                    {"url": url, "filename": document.filename,
                     "content_type": document.content_type},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        document.size_bytes = len(payload)
        document.sha256 = hashlib.sha256(payload).hexdigest()
        self._extract(document, payload)
        return document

    def _extract(self, document: FetchedDocument, payload: bytes) -> None:
        # Content decides the format, never the extension — 나라장터 serves HWPML
        # under a .hwp name, and Backend's extractor rejects those outright.
        if is_hwpml(payload[:4096]):
            try:
                document.text, document.blocks = extract_hwpml(payload)
                document.extractor = "hwpml"
            except Exception as error:  # noqa: BLE001 - one bad file, not a crash
                document.error = f"HWPML 파싱 실패: {type(error).__name__}"
            return

        from ...services.document_extraction import (
            UnsupportedDocumentError,
            extract_document,
        )

        try:
            result = extract_document(
                io.BytesIO(payload),
                filename=document.filename,
                content_type=document.content_type,
            )
        except (UnsupportedDocumentError, ValueError) as error:
            document.error = f"추출 실패: {error}"
            return
        except Exception as error:  # noqa: BLE001 - keep the run going
            document.error = f"추출 실패: {type(error).__name__}: {error}"
            return

        document.extractor = result.extractor
        document.text = result.text
        document.blocks = list(result.blocks)


class CachedDocumentSource:
    """Serve only what has already been downloaded — no network at all."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._inner = G2BDocumentSource(cache_dir=cache_dir)

    def fetch(self, item: dict[str, Any]) -> list[FetchedDocument]:
        notice_no = extract_notice_facts(item).notice_no or "unknown"
        documents: list[FetchedDocument] = []
        for url, filename in _document_targets(item):
            cache_path = self._inner._cache_path(notice_no, url)
            if cache_path.exists():
                documents.append(self._inner._fetch_one(notice_no, url, filename))
        return documents


def merge_blocks(documents: list[FetchedDocument]) -> list[dict[str, Any]]:
    """Renumber blocks across documents so chunk ids stay unique in one run."""
    merged: list[dict[str, Any]] = []
    for document in documents:
        for block in document.blocks:
            merged.append({**block, "block_index": len(merged)})
    return merged


def merged_text(documents: list[FetchedDocument]) -> str:
    return "\n".join(document.text for document in documents if document.extracted)
