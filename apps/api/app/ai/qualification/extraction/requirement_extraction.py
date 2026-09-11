"""Eligibility requirement extraction over semantic chunks.

The production boundary is:

    backend extracted_blocks
        -> canonical source blocks
        -> semantic chunks
        -> structured extractor (LLM adapter supplied by caller)
        -> validated extraction slots

The LLM extracts source text only. Deterministic code validates, normalizes,
resolves canonical values, and later judges them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

StructuredExtractor = Callable[[str, str, dict[str, Any]], dict[str, Any]]

_SECTION_HEADER_KEYWORDS = (
    "참가자격",
    "입찰참가",
    "자격요건",
    "참가 자격",
    "신청자격",
    "제한사항",
)

_FALLBACK_REQUIREMENT_KEYWORDS = (
    *_SECTION_HEADER_KEYWORDS,
    "실적",
    "면허",
    "인증",
    "등록",
    "소재",
    "지역",
    "인력",
    "업종",
    "업태",
    "경험",
    "분야",
    "소상공인",
    "소기업",
    "중소기업",
    "중견기업",
    "대기업",
)

_DETAIL_RAW_FIELDS = (
    "기간_raw",
    "금액_raw",
    "건수_raw",
    "업종_raw",
    "경험분야_raw",
    "지역_raw",
    "인원_raw",
    "인력역할_raw",
    "등록인증_raw",
    "발급기관_raw",
    "기업규모_raw",
    "실적기관_raw",
)


def _nullable_source_string(description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


SLOT_SCHEMA: dict[str, Any] = {
    "name": "eligibility_slots",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "유형": {
                            "type": "string",
                            "enum": [
                                "실적요건",
                                "인력요건",
                                "인증요건",
                                "면허요건",
                                "등록요건",
                                "지역요건",
                                "업종요건",
                                "경험분야요건",
                                "기업규모요건",
                                "기타요건",
                            ],
                        },
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
                    },
                    "required": ["유형", "raw", *_DETAIL_RAW_FIELDS, "근거조항"],
                },
            }
        },
        "required": ["requirements"],
    },
}

SYSTEM_PROMPT = """너는 입찰공고 RFP에서 참가자격 요건을 추출하는 도구다. 규칙:
1. 본문에 명시된 요건만 추출한다. 없는 요건을 만들어내지 마라. 없으면 빈 배열.
2. raw에는 원문 문장을 그대로 담는다. 요약하거나 수치·코드·enum으로 변환하지 마라.
3. 모든 *_raw 필드는 제공된 원문 표현을 그대로 담고, 해당 표현이 없으면 null로 둔다.
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


def _is_top_level(chunk: dict[str, Any]) -> bool:
    label = chunk.get("clause_label")
    return bool(label) and bool(_TOP_LEVEL_LABEL_RE.match(str(label).strip()))


def _chunk_document_id(chunk: dict[str, Any]) -> str | None:
    document_ids = {str(block.get("document_id")) for block in list(chunk.get("source_blocks") or []) if block.get("document_id")}
    return next(iter(document_ids)) if len(document_ids) == 1 else None


def _heading_text(chunk: dict[str, Any]) -> str:
    text = (chunk.get("text") or "").strip()
    return text.splitlines()[0] if text else ""


def _is_eligibility_section_anchor(chunk: dict[str, Any]) -> bool:
    if not _is_top_level(chunk):
        return False
    heading = _heading_text(chunk)
    return any(keyword in heading for keyword in _SECTION_HEADER_KEYWORDS)


def select_eligibility_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select eligibility sections and their children without crossing documents."""
    selected: dict[int, dict[str, Any]] = {}
    anchors = [index for index, chunk in enumerate(chunks) if _is_eligibility_section_anchor(chunk)]

    for index in anchors:
        anchor = chunks[index]
        selected[index] = anchor
        anchor_document_id = _chunk_document_id(anchor)
        for child_index in range(index + 1, len(chunks)):
            candidate = chunks[child_index]
            candidate_document_id = _chunk_document_id(candidate)
            if anchor_document_id is not None and candidate_document_id is not None and candidate_document_id != anchor_document_id:
                break
            if _is_top_level(candidate):
                break
            selected[child_index] = candidate

    anchored_documents = {_chunk_document_id(chunks[index]) for index in anchors}
    fallback_keywords = _FALLBACK_REQUIREMENT_KEYWORDS[len(_SECTION_HEADER_KEYWORDS):] if anchors else _FALLBACK_REQUIREMENT_KEYWORDS
    for index, chunk in enumerate(chunks):
        if _chunk_document_id(chunk) not in anchored_documents and any(keyword in (chunk.get("text") or "") for keyword in fallback_keywords):
            selected[index] = chunk
    return [selected[index] for index in sorted(selected)] if selected else chunks


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _normalize_reference(value: str) -> str:
    return re.sub(r"^(?:조항|제)\s*", "", value.strip()).rstrip(".)조항 ")


_REFERENCE_SPLIT_RE = re.compile(r"[,、·]|\s+및\s+|\s+과\s+|\s+와\s+")


def _reference_parts(reference: str) -> list[str]:
    return [part.strip() for part in _REFERENCE_SPLIT_RE.split(reference) if part.strip()]


def classify_clause_reference(
    reference: str,
    chunks: list[dict[str, Any]],
    source_chunk: dict[str, Any] | None,
) -> str:
    """Classify a model-supplied reference without discarding grounded text."""
    parts = _reference_parts(reference)
    if not parts:
        return "UNVERIFIED"

    source_labels: set[str] = set()
    if source_chunk and source_chunk.get("clause_label"):
        source_labels.add(str(source_chunk["clause_label"]))
    source_text = (source_chunk.get("text") or "") if source_chunk else ""
    if source_labels and all(
        part in source_labels or _normalize_reference(part) in source_labels
        for part in parts
    ):
        return "DOCUMENT_CLAUSE"
    if source_text and all(
        re.search(
            r"(?m)^\s*" + re.escape(_normalize_reference(part)) + r"(?:[.)\s]|$)",
            source_text,
        )
        for part in parts
    ):
        return "DOCUMENT_CLAUSE"

    haystack = _squash(source_text)
    if not haystack:
        haystack = "".join(_squash(chunk.get("text") or "") for chunk in chunks)
    if haystack and all(_squash(part) in haystack for part in parts):
        return "STATUTE"
    return "UNVERIFIED"


def _find_source_chunk(raw: str, chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    probe = _squash(raw)
    if not probe:
        return None
    for chunk in chunks:
        if probe in _squash(chunk.get("text") or ""):
            return chunk
    return None


def validate_extracted_slot(slot: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[bool, str, dict[str, Any] | None]:
    """Reject unsupported source text; clear unverified document locations."""
    raw = (slot.get("raw") or "").strip()
    if not raw:
        return False, "raw 비어 있음", None

    source_chunk = _find_source_chunk(raw, chunks)
    if source_chunk is None:
        return False, "raw가 본문에 존재하지 않음(과잉 추출 의심)", None

    source_text = _squash(source_chunk.get("text") or "")
    for field_name in _DETAIL_RAW_FIELDS:
        detail = (slot.get(field_name) or "").strip()
        if detail and _squash(detail) not in source_text:
            return False, f"{field_name}가 본문에 존재하지 않음(과잉 추출 의심)", source_chunk

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
    if "_raw가 본문에 존재하지 않음" in reason:
        return "DETAIL_NOT_FOUND_IN_SOURCE"
    return "SOURCE_VALIDATION_FAILED"


def build_extraction_body(chunks: list[dict[str, Any]], *, max_chars: int | None = 32_000) -> str:
    parts: list[str] = []
    for chunk in chunks:
        document_id = _chunk_document_id(chunk) or "(문서미상)"
        clause_label = chunk.get("clause_label") or "(라벨없음)"
        parts.append(f"[문서 {document_id} | 조항 {clause_label}]\n{chunk.get('text') or ''}")
    return "\n\n".join(parts)[:max_chars]


def extract_legacy_slots(chunks: list[dict[str, Any]], *, structured_extract: StructuredExtractor, max_retry: int = 1) -> dict[str, Any]:
    """Run structured extraction and source-grounding validation."""
    target = select_eligibility_chunks(chunks)
    full_body = build_extraction_body(target, max_chars=None)
    body = full_body[:32_000]
    last_notes = ""
    last_rejected: list[dict[str, str]] = []

    for attempt in range(max_retry + 1):
        try:
            result = structured_extract(SYSTEM_PROMPT, body, SLOT_SCHEMA)
        except Exception as error:
            return {"slots": [], "dropped_requirements": last_rejected, "status": "failed", "notes": f"구조화 추출 호출 실패: {type(error).__name__}", "target_chunk_ids": [chunk.get("chunk_id") for chunk in target]}

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        requirements = result.get("requirements", []) if isinstance(result, dict) else []

        for extracted in requirements:
            slot = dict(extracted)
            valid, reason, source_chunk = validate_extracted_slot(slot, target)
            if not valid:
                rejected.append(
                    {
                        "raw": str(slot.get("raw") or ""),
                        "reason_code": _rejection_reason_code(reason),
                    }
                )
                continue
            if source_chunk is not None:
                slot["_source_chunk_id"] = source_chunk.get("chunk_id")
                slot["_source_blocks"] = list(source_chunk.get("source_blocks") or [])
            accepted.append(slot)

        if rejected:
            last_rejected = rejected

        if accepted or not requirements:
            reported_rejections = rejected or (last_rejected if not requirements else [])
            truncated = len(full_body) > len(body)
            notes = ([f"검증 탈락 {len(reported_rejections)}건"] if reported_rejections else [])
            if truncated:
                notes.append("입력 길이 제한으로 선택된 원문 일부를 분석하지 못했습니다.")
            return {"slots": accepted, "dropped_requirements": reported_rejections, "status": "partial" if reported_rejections or truncated else "ok", "notes": " ".join(notes), "target_chunk_ids": [chunk.get("chunk_id") for chunk in target]}

        last_notes = f"전 슬롯 검증 탈락(시도 {attempt + 1})"

    return {"slots": [], "dropped_requirements": last_rejected, "status": "failed", "notes": last_notes, "target_chunk_ids": [chunk.get("chunk_id") for chunk in target]}
