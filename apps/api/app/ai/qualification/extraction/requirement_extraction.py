"""Legacy extraction with source-owned quotes and same-clause detail validation.

Legacy remains an explicit compatibility strategy. It does not infer cross-clause
relationships or silently recover codes after dropping exception text.
"""
from __future__ import annotations
import re
import unicodedata
from collections.abc import Callable
from typing import Any
from .review_grounding import SourceQuoteError, resolve_source_quote

LEGACY_GROUNDING_VERSION = "qualification-legacy-grounding-v2"
StructuredExtractor = Callable[[str, str, dict[str, Any]], dict[str, Any]]
_SECTION_HEADER_KEYWORDS = ("참가자격", "입찰참가", "자격요건", "참가 자격", "신청자격", "제한사항")
_FALLBACK_REQUIREMENT_KEYWORDS = (*_SECTION_HEADER_KEYWORDS, "실적", "면허", "인증", "등록", "소재", "지역", "인력",
    "업종", "업태", "경험", "분야", "소상공인", "소기업", "중소기업", "중견기업", "대기업")
_DETAIL_RAW_FIELDS = ("기간_raw", "금액_raw", "건수_raw", "업종_raw", "경험분야_raw", "지역_raw", "인원_raw",
    "인력역할_raw", "등록인증_raw", "발급기관_raw", "기업규모_raw", "실적기관_raw")


def _nullable_source_string(description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


SLOT_SCHEMA: dict[str, Any] = {"name": "eligibility_slots", "schema": {
    "type": "object", "additionalProperties": False, "properties": {"requirements": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
            "유형": {"type": "string", "enum": ["실적요건", "인력요건", "인증요건", "면허요건", "등록요건", "지역요건", "업종요건", "경험분야요건", "기업규모요건", "기타요건"]},
            "raw": {"type": "string", "description": "요건 원문 그대로. 요약·변형 금지"},
            "기간_raw": _nullable_source_string("기간 표현 원문. 없으면 null"),
            "금액_raw": _nullable_source_string("금액 표현 원문. 없으면 null"),
            "건수_raw": _nullable_source_string("실적 건수 표현 원문. 없으면 null"),
            "업종_raw": _nullable_source_string("업종·업태 제한 원문 명칭. 없으면 null"),
            "경험분야_raw": _nullable_source_string("과거 실적/경험에서 요구하는 분야 원문. 없으면 null"),
            "지역_raw": _nullable_source_string("지역·소재지 제한의 원문 명칭. 없으면 null"),
            "인원_raw": _nullable_source_string("필요 인원 수 표현 원문. 없으면 null"),
            "인력역할_raw": _nullable_source_string("요구 인력 역할·자격·등급 원문. 없으면 null"),
            "등록인증_raw": _nullable_source_string("등록·면허·인증 명칭 원문. 없으면 null"),
            "발급기관_raw": _nullable_source_string("등록·면허·인증 발급기관 원문. 없으면 null"),
            "기업규모_raw": _nullable_source_string("소상공인·소기업·중소기업·중견기업 등 기업규모 원문. 없으면 null"),
            "실적기관_raw": _nullable_source_string("실적 대상 발주기관·고객 범위 원문. 없으면 null"),
            "근거조항": _nullable_source_string("이 요건이 적힌 문서 자체의 조항 번호/라벨(예: 2, 3.1, 제5조). 인용된 법령 조문은 제외. 없으면 null"),
        }, "required": ["유형", "raw", *_DETAIL_RAW_FIELDS, "근거조항"]}}}, "required": ["requirements"]}}

SYSTEM_PROMPT = """너는 입찰공고 RFP에서 참가자격 요건을 추출하는 도구다. 규칙:
1. 본문에 명시된 요건만 추출한다. 없는 요건을 만들어내지 마라. 없으면 빈 배열.
2. raw에는 원문 문장을 그대로 담는다. 요약하거나 수치·코드·enum으로 변환하지 마라.
3. 모든 *_raw 필드는 raw에 담은 같은 조건의 연속 원문 구간이어야 한다. 다른 조항의 값을 가져오거나 쉼표·세미콜론으로 떨어진 표현을 이어붙이지 않는다.
4. 실적요건은 기간/금액/건수/경험분야/실적기관 표현을 같은 슬롯에 함께 담을 수 있다.
5. 업종·업태 자체가 참가 제한이면 유형=업종요건, 업종_raw에 원문 명칭을 담는다. 등록·면허·인증 보유 여부와 혼동하지 마라.
6. 금액·건수와 독립적으로 특정 경험 분야 보유 자체를 요구하는 경우에만 유형=경험분야요건을 사용한다.
7. 인력요건은 인원_raw와 인력역할_raw를 가능한 범위에서 분리한다.
8. 인증·면허·등록 요건은 '특정 등록/면허/인증을 보유 또는 완료해야 한다'는 단일 사실일 때만 각각 인증요건/면허요건/등록요건으로 분류한다. 등록인증_raw에는 실제 명칭을 담는다.
9. 소재지 제한은 유형=지역요건, 지역_raw에 원문 지역명을 담는다.
10. 소상공인·소기업·중소기업·중견기업·대기업 등 규모 제한은 유형=기업규모요건, 기업규모_raw에 원문 표현을 담는다. Backend enum으로 변환하지 마라.
11. 근거조항에는 이 요건이 적힌 문서 자체의 조항 번호(예: 2, 3.1, 제5조)만 적는다. 요건 문장이 인용하는 법령 조문은 문서 위치가 아니다. 문서 조항 번호를 알 수 없으면 null로 둔다.
12. 공동수급/공동계약 구성원·대표사 관계, 대표자 중복, 변경등록, 입찰무효, 법령상 예외, '아니어야 한다/하지 않아야 한다' 같은 부정 조건, 여러 조건이 '또는/다만/각 호'로 결합된 복합 절차 조건은 단순 등록·면허·인증 보유 요건으로 축약하지 마라. 닫힌 canonical 유형 하나로 안전하게 표현할 수 없으면 유형=기타요건으로 둔다.
13. 원문에 여러 독립적인 원자 조건이 명시되어 있으면 한 문장을 임의 요약하지 말고 각각 별도 requirement로 추출한다. 단, 논리 관계를 잃게 되는 복합조건은 억지로 분해하지 말고 기타요건으로 둔다.
14. 참가자격 섹션뿐 아니라 첨부 제안요청서·과업지시서에서 명시적으로 참가 자격을 요구하는 실적/인력/업종/지역/기업규모 조건도 추출 대상이다."""

_TOP_LEVEL_LABEL_RE = re.compile(r"^(?:\d+|[가-힣]|[IVXivx]+|제\d+조(?:의\d+)?|제\d+장)$")
_LABEL_RANK_PATTERNS = (
    (re.compile(r"^(?:제\d+장|제\d+조(?:의\d+)?)$"), 0),
    (re.compile(r"^(?:\d+|[IVXivx]+)$"), 10),
    (re.compile(r"^[가-힣]$"), 20), (re.compile(r"^\d+\)$"), 30),
    (re.compile(r"^[가-힣]\)$"), 40), (re.compile(r"^\(\d+\)$"), 50))
_HEADING_MARKER_RE = re.compile(
    r"^\s*(?:(?P<paren_num>\(\d+\))|(?P<num_paren>\d+\))|(?P<han_paren>[가-힣]\))"
    r"|(?P<dotted>\d+(?:\.\d+)+)|(?P<num>\d+)\s*[.．]|(?P<han>[가-힣])\s*[.．]"
    r"|(?P<article>제\d+(?:장|조(?:의\d+)?)))")
_MARKER_RANK = {"article": 0, "num": 10, "han": 20, "num_paren": 30, "han_paren": 40, "paren_num": 50}


def _label_rank(chunk: dict[str, Any]) -> int | None:
    label = str(chunk.get("clause_label") or "").strip()
    if not label:
        return None
    first = _heading_text(chunk)
    if re.match(r"^\s*[12]\d{3}[./-]\s*\d{1,2}[./-]\s*\d{1,2}(?:[.]|\s|$)", first):
        return None
    marker = _HEADING_MARKER_RE.match(first)
    if marker:
        return 10 + marker.group("dotted").count(".") if marker.lastgroup == "dotted" else _MARKER_RANK[marker.lastgroup]
    return next((rank for pattern, rank in _LABEL_RANK_PATTERNS if pattern.match(label)), None)


def _is_top_level(chunk: dict[str, Any]) -> bool:
    label = chunk.get("clause_label")
    return bool(label) and bool(_TOP_LEVEL_LABEL_RE.match(str(label).strip()))


def _chunk_document_id(chunk: dict[str, Any]) -> str | None:
    ids = {str(b.get("document_id")) for b in list(chunk.get("source_blocks") or []) if b.get("document_id")}
    return next(iter(ids)) if len(ids) == 1 else None


def _heading_text(chunk: dict[str, Any]) -> str:
    text = (chunk.get("text") or "").strip()
    return text.splitlines()[0] if text else ""


def _is_eligibility_section_anchor(chunk: dict[str, Any]) -> bool:
    return _label_rank(chunk) is not None and any(k in _heading_text(chunk) for k in _SECTION_HEADER_KEYWORDS)


def select_eligibility_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = {}
    anchors = [i for i, c in enumerate(chunks) if _is_eligibility_section_anchor(c)]
    for i in anchors:
        anchor = chunks[i]
        selected[i] = anchor
        document, rank = _chunk_document_id(anchor), _label_rank(anchor)
        for j in range(i + 1, len(chunks)):
            child = chunks[j]
            doc, child_rank = _chunk_document_id(child), _label_rank(child)
            if document is not None and doc is not None and document != doc:
                break
            if child_rank is not None and (rank is None or child_rank <= rank):
                break
            selected[j] = child
    anchored_documents = {_chunk_document_id(chunks[i]) for i in anchors}
    keywords = _FALLBACK_REQUIREMENT_KEYWORDS[len(_SECTION_HEADER_KEYWORDS):] if anchors else _FALLBACK_REQUIREMENT_KEYWORDS
    for i, chunk in enumerate(chunks):
        if _chunk_document_id(chunk) not in anchored_documents and any(k in (chunk.get("text") or "") for k in keywords):
            selected[i] = chunk
    return [selected[i] for i in sorted(selected)] if selected else chunks


_GROUNDING_PUNCTUATION = str.maketrans({"․": "·", "ㆍ": "·", "‧": "·", "・": "·", "‥": "·", "（": "(", "）": ")"})


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value.translate(_GROUNDING_PUNCTUATION)))


def _normalize_reference(value: str) -> str:
    return re.sub(r"^(?:조항|제)\s*", "", value.strip()).rstrip(".)조항 ")


_REFERENCE_SPLIT_RE = re.compile(r"[,、·]|\s+및\s+|\s+과\s+|\s+와\s+")


def _reference_parts(reference: str) -> list[str]:
    return [part.strip() for part in _REFERENCE_SPLIT_RE.split(reference) if part.strip()]


def classify_clause_reference(reference: str, chunks: list[dict[str, Any]], source_chunk: dict[str, Any] | None) -> str:
    parts = _reference_parts(reference)
    if not parts:
        return "UNVERIFIED"
    labels = {str(source_chunk["clause_label"])} if source_chunk and source_chunk.get("clause_label") else set()
    text = (source_chunk.get("text") or "") if source_chunk else ""
    if labels and all(p in labels or _normalize_reference(p) in labels for p in parts):
        return "DOCUMENT_CLAUSE"
    if text and all(re.search(r"(?m)^\s*" + re.escape(_normalize_reference(p)) + r"(?:[.)\s]|$)", text) for p in parts):
        return "DOCUMENT_CLAUSE"
    haystack = _squash(text) or "".join(_squash(c.get("text") or "") for c in chunks)
    return "STATUTE" if haystack and all(_squash(p) in haystack for p in parts) else "UNVERIFIED"


def _find_source_chunk(raw: str, chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = []
    for chunk in chunks:
        try:
            resolve_source_quote(chunk.get("text") or "", raw)
        except SourceQuoteError:
            continue
        matches.append(chunk)
    return matches[0] if len(matches) == 1 else None


def validate_extracted_slot(slot: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[bool, str, dict[str, Any] | None]:
    """공고 어디엔가 있는 값이 아니라 해당 raw 구간의 실제 인용을 확인한다."""
    raw = (slot.get("raw") or "").strip()
    if not raw:
        return False, "raw 비어 있음", None
    source_chunk = _find_source_chunk(raw, chunks)
    if source_chunk is None:
        return False, "raw가 본문에 존재하지 않음(과잉 추출 또는 모호한 인용)", None
    restored = resolve_source_quote(source_chunk.get("text") or "", raw)
    grounded = {}
    for field in _DETAIL_RAW_FIELDS:
        detail = (slot.get(field) or "").strip()
        if not detail:
            continue
        try:
            grounded[field] = resolve_source_quote(restored.quote, detail, base_offset=restored.start_offset)
        except SourceQuoteError as error:
            slot["_rejected_detail"] = {"field": field, "value": detail, "code": str(error)}
            return False, f"{field}가 본문에 존재하지 않음(같은 요건의 원문 범위 확인 필요)", source_chunk
    slot["raw"] = restored.quote
    slot["_grounding_basis"] = {"version": LEGACY_GROUNDING_VERSION, "coordinate_scope": "SOURCE_CHUNK",
        "raw_start": restored.start_offset, "raw_end": restored.end_offset,
        "fields": {key: {"start": span.start_offset, "end": span.end_offset, "method": span.method} for key, span in grounded.items()}}
    for key, span in grounded.items():
        slot[key] = span.quote
    reference = slot.get("근거조항")
    if reference:
        kind = classify_clause_reference(str(reference), chunks, source_chunk)
        slot["_reference_kind"] = kind
        if kind == "STATUTE":
            slot["_statute_reference"] = str(reference)
            slot["근거조항"] = None
        elif kind == "UNVERIFIED":
            slot["근거조항"] = None
    return True, "", source_chunk


def _rejection_reason_code(reason: str) -> str:
    if reason == "raw 비어 있음":
        return "MISSING_RAW"
    if reason.startswith("raw가 본문에 존재하지 않음"):
        return "RAW_NOT_FOUND_IN_SOURCE"
    return "DETAIL_NOT_FOUND_IN_SOURCE" if "_raw가 본문에 존재하지 않음" in reason else "SOURCE_VALIDATION_FAILED"


def build_extraction_body(chunks: list[dict[str, Any]], *, max_chars: int | None = 32_000) -> str:
    parts = []
    for chunk in chunks:
        doc = _chunk_document_id(chunk) or "(문서미상)"
        label = chunk.get("clause_label") or "(라벨없음)"
        parts.append(f"[문서 {doc} | 조항 {label}]\n{chunk.get('text') or ''}")
    return "\n\n".join(parts)[:max_chars]


def extract_legacy_slots(chunks: list[dict[str, Any]], *, structured_extract: StructuredExtractor, max_retry: int = 1) -> dict[str, Any]:
    target = select_eligibility_chunks(chunks)
    full_body = build_extraction_body(target, max_chars=None)
    body, last_notes, last_rejected = full_body[:32_000], "", []
    target_ids = [chunk.get("chunk_id") for chunk in target]
    for attempt in range(max_retry + 1):
        try:
            result = structured_extract(SYSTEM_PROMPT, body, SLOT_SCHEMA)
        except Exception as error:
            return {"slots": [], "dropped_requirements": last_rejected, "status": "failed",
                "notes": f"구조화 추출 호출 실패: {type(error).__name__}", "target_chunk_ids": target_ids}
        accepted, rejected = [], []
        requirements = result.get("requirements", []) if isinstance(result, dict) else []
        for extracted in requirements:
            slot = dict(extracted)
            valid, reason, chunk = validate_extracted_slot(slot, target)
            if not valid:
                item = {"raw": str(slot.get("raw") or ""), "reason_code": _rejection_reason_code(reason)}
                detail = slot.get("_rejected_detail")
                if detail:
                    item.update(detail_field=detail["field"], detail_value=detail["value"], validation_code=detail["code"])
                rejected.append(item)
                continue
            if chunk is not None:
                slot["_source_chunk_id"] = chunk.get("chunk_id")
                slot["_source_blocks"] = list(chunk.get("source_blocks") or [])
            accepted.append(slot)
        if rejected:
            last_rejected = rejected
        if accepted or not requirements:
            reported = rejected or (last_rejected if not requirements else [])
            truncated = len(full_body) > len(body)
            notes = [f"검증 탈락 {len(reported)}건"] if reported else []
            if truncated:
                notes.append("입력 길이 제한으로 선택된 원문 일부를 분석하지 못했습니다.")
            return {"slots": accepted, "dropped_requirements": reported, "status": "partial" if reported or truncated else "ok",
                "notes": " ".join(notes), "target_chunk_ids": target_ids}
        last_notes = f"전 슬롯 검증 탈락(시도 {attempt + 1})"
    return {"slots": [], "dropped_requirements": last_rejected, "status": "failed", "notes": last_notes, "target_chunk_ids": target_ids}
