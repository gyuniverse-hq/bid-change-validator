"""A runnable look at what clause review actually does.

    python -m apps.api.app.ai.demo                  캐시된 실제 공고를 검토
    python -m apps.api.app.ai.demo --fetch <공고번호>  나라장터에서 받아와 검토
    python -m apps.api.app.ai.demo --standards      예규에서 뽑아낸 기준값만 표로
    python -m apps.api.app.ai.demo --text "…"       문장 하나를 즉석에서 검토
    python -m apps.api.app.ai.demo --list           캐시된 공고 목록

No database and no model anywhere in here. Every mode but `--fetch` also needs no
network, running off two files already in the repo — the standards index and the
cached attachments — so it works with a broken DATABASE_URL and no API key. That
is most of the point: clause review is code comparing a notice against published
rules, and this shows it without anything else having to be up.

`--fetch` is the exception and needs `G2B_SERVICE_KEY`. It downloads through the
same cache, so asking for a notice twice only hits 나라장터 once.

The demo is also the honest view. It prints COMPLIANT and UNDETERMINED next to
NEEDS_REVIEW, because "we checked and it is fine" and "we could not tell" are
different answers and hiding either one flatters the pipeline.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

from ..qualification.extraction.chunking import chunk_source_blocks
from ..clause_review import (
    ClauseFinding,
    detect_patterns,
    detect_standard_diff,
    scope_for_notice,
)
from ..clause_review.standards import (
    SCOPE_LABELS,
    format_value,
    load_clauses,
    resolve_all,
)


REPO_ROOT = Path(__file__).resolve().parents[5]
STANDARDS_PATH = REPO_ROOT / "data" / "standards" / "clauses.json"
DOCUMENT_CACHE = REPO_ROOT / "data" / "demo" / "notice-documents"

WIDTH = 78
VERDICT_ORDER = {"NEEDS_REVIEW": 0, "UNDETERMINED": 1, "COMPLIANT": 2}
VERDICT_HEADING = {
    "NEEDS_REVIEW": "확인 필요",
    "UNDETERMINED": "확인 불가",
    "COMPLIANT": "적합",
}


def _out(line: str = "") -> None:
    print(line)


def _rule(char: str = "─") -> None:
    _out(char * WIDTH)


def _heading(title: str) -> None:
    _out()
    _rule("═")
    _out(f" {title}")
    _rule("═")


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return "-"
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# ── documents ────────────────────────────────────────────────────────────
def _cached_notices() -> list[Path]:
    if not DOCUMENT_CACHE.exists():
        return []
    return sorted(path for path in DOCUMENT_CACHE.iterdir() if path.is_dir())


def _read_cached_documents(directory: Path) -> list[dict[str, Any]]:
    """Text blocks from every cached attachment of one notice.

    The extractor is imported here rather than at module scope on purpose: it
    pulls in SQLAlchemy and the ORM models, and `app.ai` is meant to stay a
    library with no database underneath it. A demo may reach out; the package
    must not.
    """
    from ...services.document_extraction import extract_document

    blocks: list[dict[str, Any]] = []
    for meta_path in sorted(directory.glob("*.json")):
        payload_path = meta_path.with_suffix(".bin")
        if not payload_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        filename = meta.get("filename") or meta_path.stem
        try:
            result = extract_document(
                io.BytesIO(payload_path.read_bytes()),
                filename=filename,
                content_type=meta.get("content_type"),
            )
        except Exception as error:  # noqa: BLE001 - a demo reports, it does not raise
            _out(f"  · {_clip(filename, 52):54} 읽지 못함 ({type(error).__name__})")
            continue
        _out(f"  · {_clip(filename, 52):54} 블록 {len(result.blocks):,}개")
        blocks.extend(result.blocks)
    return blocks


# 나라장터 serves each business type from its own endpoint, and a notice number
# does not say which one it belongs to, so the lookup tries them in turn. The
# type that answers is worth keeping: it says what kind of contract this is far
# more reliably than reading the prose does.
_BUSINESS_TYPE_ORDER = ("SERVICE", "GOODS", "CONSTRUCTION", "FOREIGN", "OTHER")



def fetch_notice(notice_no: str) -> tuple[dict[str, Any], str] | None:
    """Look a notice up on 나라장터. Returns the item and its business type.

    Imported inside the function: the client reaches the network and pulls in
    settings, and `app.ai` is meant to stay a library that does neither.
    """
    from ...config import get_settings
    from ...schemas import BusinessType, NoticeInquiryType
    from ...services.g2b import G2BApiError, G2BClient

    settings = get_settings()
    service_key = settings.decoded_g2b_service_key
    if not service_key:
        _out(" G2B_SERVICE_KEY 가 설정되지 않았습니다 (.env 확인)")
        return None

    client = G2BClient(
        service_key=service_key,
        base_url=settings.g2b_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
    )
    for name in _BUSINESS_TYPE_ORDER:
        try:
            page = client.fetch_page(
                business_type=BusinessType(name),
                inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
                page_number=1,
                page_size=10,
                bid_notice_no=notice_no,
            )
        except G2BApiError as error:
            _out(f"  · {name:14} 조회 실패 ({error.code})")
            continue
        if page.items:
            return page.items[0], name
    return None


def _download_documents(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Attachments for one notice, downloaded and read into text blocks."""
    from .documents import G2BDocumentSource

    blocks: list[dict[str, Any]] = []
    for document in G2BDocumentSource(cache_dir=DOCUMENT_CACHE).fetch(item):
        if document.error:
            _out(f"  · {_clip(document.filename, 46):48} {document.error}")
            continue
        _out(
            f"  · {_clip(document.filename, 46):48} "
            f"{document.size_bytes:>9,}B  블록 {len(document.blocks):,}개"
        )
        blocks.extend(document.blocks)
    return blocks


def _chunks_from(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**chunk, "chunk_id": f"CHUNK-{index:04d}"}
        for index, chunk in enumerate(chunk_source_blocks(blocks))
    ]


# ── rendering ────────────────────────────────────────────────────────────
def _print_finding(finding: ClauseFinding) -> None:
    code = finding.category_code or "(값 없음)"
    _out(f"  [{code}]  {finding.label}")
    _out(f"      사유     {_clip(finding.reason, 66)}")

    if finding.notice_value is not None and finding.standard:
        # `notice_value_raw` is the span the normalizer read, so it can trail off
        # mid-word. The normalized figure is what was actually compared.
        notice = format_value(finding.notice_value, finding.notice_value_unit)
        standard = finding.standard.value_raw or finding.standard.value
        _out(f"      공고 값  {notice:14} 표준 {standard}")
    if finding.standard and finding.standard.clause_ref:
        _out(f"      근거     {finding.standard.clause_ref}")
    if finding.matched_text:
        _out(f"      공고 문언 “{_clip(finding.matched_text, 62)}”")
    if finding.clause_label or finding.chunk_id:
        where = " · ".join(part for part in (finding.clause_label, finding.chunk_id) if part)
        _out(f"      위치     {where}")
    if finding.details.get("drift"):
        drift = finding.details["drift"]
        _out(f"      ⚠ 예규 개정 감지  기록 {drift['recorded']} → 원문 {drift['extracted']}")
    _out()


def _print_findings(findings: list[ClauseFinding]) -> None:
    if not findings:
        _out("  검출된 조항이 없습니다.")
        return

    ordered = sorted(
        findings, key=lambda item: (VERDICT_ORDER.get(item.verdict, 3), item.rule_id)
    )
    current: str | None = None
    for finding in ordered:
        if finding.verdict != current:
            current = finding.verdict
            _out()
            _out(f"── {VERDICT_HEADING[current]} ".ljust(WIDTH, "─"))
            _out()
        _print_finding(finding)

    counts = {name: 0 for name in VERDICT_HEADING}
    for finding in findings:
        counts[finding.verdict] += 1
    _rule()
    _out(
        f" 확인 필요 {counts['NEEDS_REVIEW']}건 · "
        f"적합 {counts['COMPLIANT']}건 · "
        f"확인 불가 {counts['UNDETERMINED']}건"
    )


# ── commands ─────────────────────────────────────────────────────────────
def show_standards(clauses: list[dict[str, Any]]) -> None:
    """What each rule compares against, per kind of contract.

    Nothing here is written in the codebase. Every value on this table was read
    out of the rule text a moment ago, which is why a blank means "the rules say
    nothing about this for this contract" rather than "we forgot".
    """
    _heading("예규·법령에서 읽어온 기준값")
    _out(" 코드에 적힌 숫자가 아니라, 방금 원문에서 뽑은 값입니다.")

    for scope, chapter in SCOPE_LABELS.items():
        _out()
        _out(f" [{scope}]  {chapter}")
        _rule()
        for rule_id, resolved in resolve_all(clauses, contract_scope=scope).items():
            if resolved["status"] == "out_of_scope":
                _out(f"   {rule_id:24} —  (이 계약 종류에는 해당 조문 없음)")
                continue
            if resolved["status"] != "ok":
                _out(f"   {rule_id:24} !!  읽기 실패: {resolved['status']}")
                continue
            value = resolved["raw"] or "-"
            # 1천분의 1.25 is the only figure whose own wording does not say what
            # it is compared as, so that one carries its percentage alongside.
            if "천분의" in value and resolved["value"] is not None:
                value = f"{value} (= {resolved['value']}%)"
            _out(f"   {rule_id:24} {_clip(value, 32):34} {resolved['ref']}")


def review_text(clauses: list[dict[str, Any]], text: str, scope: str | None) -> None:
    _heading("문장 검토")
    _out(f" 입력  “{_clip(text, 66)}”")
    chunks = [{"chunk_id": "CHUNK-0000", "clause_label": None, "text": text}]
    used = scope or "COMMON"
    _out(f" 계약 종류  {used}   ({SCOPE_LABELS[used]})")
    if scope is None:
        _out("   └ 한 문장으로는 계약 종류를 알 수 없어 공통 기준을 씁니다.")
        _out("     SW 기준으로 보시려면 --scope SOFTWARE 를 붙이세요.")

    findings = detect_standard_diff(chunks, clauses, contract_scope=used)
    findings += detect_patterns(chunks)
    _print_findings(findings)


def _review_blocks(
    clauses: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    *,
    business_type: str | None = None,
) -> None:
    if not blocks:
        _out()
        _out(" 읽을 수 있는 문서가 없습니다.")
        return

    chunks = _chunks_from(blocks)
    scope = scope_for_notice(chunks, business_type=business_type)
    total_chars = sum(len(chunk["text"]) for chunk in chunks)

    _out()
    _out(f" 청크       {len(chunks):,}개 · {total_chars:,}자")
    _out(f" 계약 종류   {scope}  ({SCOPE_LABELS[scope]})")
    _out("   └ 공고 본문에서 판별했습니다. 종류에 따라 적용 조문이 달라집니다.")


    findings = detect_standard_diff(chunks, clauses, contract_scope=scope)
    findings += detect_patterns(chunks)
    _print_findings(findings)


def review_notice(clauses: list[dict[str, Any]], directory: Path) -> None:
    _heading(f"공고 조항검토 (캐시) — {directory.name}")
    _out(" 첨부 문서")
    _review_blocks(clauses, _read_cached_documents(directory))


def fetch_and_review(clauses: list[dict[str, Any]], notice_no: str) -> int:
    _heading(f"공고 조항검토 (나라장터 조회) — {notice_no}")
    _out(" 공고 조회")
    found = fetch_notice(notice_no)
    if found is None:
        _out()
        _out(" 해당 공고번호를 찾지 못했습니다.")
        _out(" 공고번호는 하이픈 없이 넣어주세요 (예: R26BK01705963).")
        return 1

    item, business_type = found
    _out(f"  · {business_type} 에서 찾았습니다")
    _out()
    _out(f" 공고명     {_clip(item.get('bidNtceNm'), 60)}")
    _out(f" 공고기관    {_clip(item.get('ntceInsttNm'), 40)}")
    _out(f" 수요기관    {_clip(item.get('dminsttNm'), 40)}")
    _out(f" 업무구분    {business_type}")
    _out()
    _out(" 첨부 문서 (이미 받은 파일은 캐시에서 씁니다)")
    _review_blocks(clauses, _download_documents(item), business_type=business_type)
    return 0


def list_notices() -> None:
    _heading("캐시된 공고")
    notices = _cached_notices()
    if not notices:
        _out(f" {DOCUMENT_CACHE} 아래에 캐시된 공고가 없습니다.")
        return
    for directory in notices:
        count = len(list(directory.glob("*.bin")))
        _out(f"  {directory.name}    첨부 {count}건")
    _out()
    _out(" 특정 공고를 보시려면:  --notice <공고번호>")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.api.app.ai.demo",
        description="조항검토를 DB·네트워크·모델 없이 실행해 봅니다.",
    )
    parser.add_argument("--standards", action="store_true", help="기준값 표만 출력")
    parser.add_argument("--text", help="문장 하나를 즉석에서 검토")
    parser.add_argument("--fetch", help="나라장터에서 공고번호로 받아와 검토")
    parser.add_argument("--notice", help="캐시된 공고번호 (기본: 캐시된 첫 번째)")
    parser.add_argument("--list", action="store_true", help="캐시된 공고 목록")
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPE_LABELS),
        help="계약 종류를 직접 지정 (--text 와 함께 쓸 때 유용)",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp949
        sys.stdout.reconfigure(encoding="utf-8")

    if args.list:
        list_notices()
        return 0

    if not STANDARDS_PATH.exists():
        _out(f"표준 조문 인덱스가 없습니다: {STANDARDS_PATH}")
        _out("먼저 `python scripts/build_standard_clauses.py` 를 실행하세요.")
        return 1
    clauses = load_clauses(STANDARDS_PATH)

    if args.standards:
        show_standards(clauses)
        return 0

    if args.text:
        review_text(clauses, args.text, args.scope)
        return 0

    if args.fetch:
        return fetch_and_review(clauses, args.fetch.strip())

    notices = _cached_notices()
    if args.notice:
        directory = DOCUMENT_CACHE / args.notice
        if not directory.is_dir():
            _out(f"캐시에 없는 공고입니다: {args.notice}")
            list_notices()
            return 1
    elif notices:
        directory = notices[0]
    else:
        _out("캐시된 공고가 없어 기준값 표만 보여드립니다.")
        show_standards(clauses)
        return 0

    review_notice(clauses, directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
