"""Eligibility requirement extraction over semantic chunks.

This module ports the useful extraction/guardrail behavior from the existing
`bid-change-validator-llm-rag/eligibility/slots.py` PoC without coupling the
backend package to a specific LLM SDK.

The production boundary is:

    backend extracted_blocks
        -> canonical source blocks
        -> semantic chunks
        -> structured extractor (LLM adapter supplied by caller)
        -> validated extraction slots

Numeric normalization and Canonical Requirement conversion remain separate code
steps. The LLM extracts source text; deterministic code validates, normalizes,
and later judges it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

StructuredExtractor = Callable[[str, str, dict[str, Any]], dict[str, Any]]

# Strong section anchors. These are used only against a top-level chunk heading,
# not arbitrary body text, so phrases such as "실적증명서 제출" or
# "자격요건이 아니다" do not accidentally become eligibility sections.
_SECTION_HEADER_KEYWORDS = (
    "참가자격",
    "입찰참가",
    "자격요건",
    "참가 자격",
    "신청자격",
    "제한사항",
)

# Used only when no explicit eligibility section heading exists in the document.
# This preserves recall for loosely structured documents while keeping the normal
# path conservative.
_FALLBACK_REQUIREMENT_KEYWORDS = (
    *_SECTION_HEADER_KEYWORDS,
    "실적",
    "면허",
    "인증",
    "소재",
    "지역",
    "인력",
    "업종",
    "업태",
    "경험",
    "분야",
)

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
                                "지역요건",
                                "업종요건",
                                "경험분야요건",
                                "기타요건",
                            ],
                        },
                        "raw": {
                            "type": "string",
                            "description": "요건 원문 그대로. 요약·변형 금지",
                        },
                        "기간_raw": {
                            "type": ["string", "null"],
                            "description": "기간 표현 원문. 없으면 null",
                        },
                        "금액_raw": {
                            "type": ["string", "null"],
                            "description": "금액 표현 원문. 없으면 null",
                        },
                        "업종_raw": {
                            "type": ["string", "null"],
                            "description": "업종·업태 제한의 원문 명칭. 없으면 null",
                        },
                        "경험분야_raw": {
                            "type": ["string", "null"],
                            "description": "과거 실적/경험에서 요구하는 분야 원문. 없으면 null",
                        },
                        "근거조항": {
                            "type": ["string", "null"],
                            "description": "제공된 텍스트에서 확인되는 조항 번호/라벨",
                        },
                    },
                    # OpenAI strict JSON schema requires every property to be
                    # required; optional semantic fields are represented as null.
                    "required": [
                        "유형",
                        "raw",
                        "기간_raw",
                        "금액_raw",
                        "업종_raw",
                        "경험분야_raw",
                        "근거조항",
                    ],
                },
            }
        },
        "required": ["requirements"],
    },
}

SYSTEM_PROMPT = """너는 입찰공고 RFP에서 참가자격 요건을 추출하는 도구다. 규칙:
1. 본문에 명시된 요건만 추출한다. 없는 요건을 만들어내지 마라. 없으면 빈 배열.
2. raw에는 원문 문장을 그대로 담는다. 요약하거나 수치를 변환하지 마라.
3. 기간_raw/금액_raw에는 원문 표현 문자열만 담는다. 숫자로 바꾸지 마라.
4. 업종·업태 자체가 참가 제한이면 유형=업종요건, 업종_raw에 원문 명칭을 담는다. 면허·인증의 보유 여부와 혼동하지 마라.
5. 실적요건이 특정 사업·기술·서비스 분야의 과거 경험을 요구하면 경험분야_raw에 그 원문 표현을 담는다. 금액·건수와 같은 문장에 있으면 실적요건 한 건에 함께 담는다.
6. 금액·건수와 독립적으로 특정 경험 분야 보유 자체를 요구하는 경우에만 유형=경험분야요건을 사용한다.
7. 근거조항에는 그 요건이 적힌 조항 번호를 담되, 제공된 텍스트에서 확인되는 것만 적는다."""

_TOP_LEVEL_LABEL_RE = re.compile(r"^(?:\d+|[가-힣]|[IVXivx]+|제\d+조(?:의\d+)?|제\d+장)$")


def _is_top_level(chunk: dict[str, Any]) -> bool:
    label = chunk.get("clause_label")
    return bool(label) and bool(_TOP_LEVEL_LABEL_RE.match(str(label).strip()))


def _chunk_document_id(chunk: dict[str, Any]) -> str | None:
    """Resolve the single Backend document id represented by a semantic chunk."""
    document_ids = {
        str(block.get("document_id"))
        for block in list(chunk.get("source_blocks") or [])
        if block.get("document_id")
    }
    if len(document_ids) == 1:
        return next(iter(document_ids))
    return None


def _heading_text(chunk: dict[str, Any]) -> str:
    """Return only the first semantic line used as the section heading."""
    text = (chunk.get("text") or "").strip()
    return text.splitlines()[0] if text else ""


def _is_eligibility_section_anchor(chunk: dict[str, Any]) -> bool:
    if not _is_top_level(chunk):
        return False
    heading = _heading_text(chunk)
    return any(keyword in heading for keyword in _SECTION_HEADER_KEYWORDS)


def select_eligibility_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select eligibility sections and their children without crossing documents.

    Normal path:
    1. find explicit top-level eligibility section headings;
    2. include their child clauses until the next top-level heading;
    3. stop immediately at a Backend document boundary.

    Only when no explicit section heading exists do we fall back to keyword-based
    retrieval. This avoids false positives such as a later "제출서류" section that
    merely contains "실적증명서".
    """
    selected: dict[int, dict[str, Any]] = {}
    anchors = [
        index
        for index, chunk in enumerate(chunks)
        if _is_eligibility_section_anchor(chunk)
    ]

    for index in anchors:
        anchor = chunks[index]
        selected[index] = anchor
        anchor_document_id = _chunk_document_id(anchor)

        for child_index in range(index + 1, len(chunks)):
            candidate = chunks[child_index]
            candidate_document_id = _chunk_document_id(candidate)

            if (
                anchor_document_id is not None
                and candidate_document_id is not None
                and candidate_document_id != anchor_document_id
            ):
                break

            if _is_top_level(candidate):
                break

            selected[child_index] = candidate

    if selected:
        return [selected[index] for index in sorted(selected)]

    fallback = [
        chunk
        for chunk in chunks
        if any(
            keyword in (chunk.get("text") or "")
            for keyword in _FALLBACK_REQUIREMENT_KEYWORDS
        )
    ]
    return fallback[:8] if fallback else chunks[:8]


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _normalize_reference(value: str) -> str:
    return re.sub(r"^(?:조항|제)\s*", "", value.strip()).rstrip(".)조항 ")


def _find_source_chunk(raw: str, chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    probe = _squash(raw)
    if not probe:
        return None
    prefix = probe[:40]
    for chunk in chunks:
        if prefix in _squash(chunk.get("text") or ""):
            return chunk
    return None


def validate_extracted_slot(
    slot: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> tuple[bool, str, dict[str, Any] | None]:
    """Reject unsupported raw text, detail fields, or clause references."""
    raw = (slot.get("raw") or "").strip()
    if not raw:
        return False, "raw 비어 있음", None

    source_chunk = _find_source_chunk(raw, chunks)
    if source_chunk is None:
        return False, "raw가 본문에 존재하지 않음(과잉 추출 의심)", None

    source_text = _squash(source_chunk.get("text") or "")
    for field_name in ("기간_raw", "금액_raw", "업종_raw", "경험분야_raw"):
        detail = (slot.get(field_name) or "").strip()
        if detail and _squash(detail) not in source_text:
            return (
                False,
                f"{field_name}가 본문에 존재하지 않음(과잉 추출 의심)",
                source_chunk,
            )

    reference = slot.get("근거조항")
    if reference:
        normalized_reference = _normalize_reference(str(reference))
        labels = {
            str(chunk["clause_label"])
            for chunk in chunks
            if chunk.get("clause_label")
        }
        appears_in_heading_text = any(
            normalized_reference in (chunk.get("text") or "")[:120]
            for chunk in chunks
        )
        if labels and normalized_reference not in labels and not appears_in_heading_text:
            return (
                False,
                f"근거조항 '{reference}'가 실제 조항 라벨과 불일치",
                source_chunk,
            )

    return True, "", source_chunk


def build_extraction_body(chunks: list[dict[str, Any]], *, max_chars: int = 24_000) -> str:
    """Build LLM input while exposing Backend document identity for disambiguation."""
    parts: list[str] = []
    for chunk in chunks:
        document_id = _chunk_document_id(chunk) or "(문서미상)"
        clause_label = chunk.get("clause_label") or "(라벨없음)"
        parts.append(
            f"[문서 {document_id} | 조항 {clause_label}]\n{chunk.get('text') or ''}"
        )
    return "\n\n".join(parts)[:max_chars]


def extract_legacy_slots(
    chunks: list[dict[str, Any]],
    *,
    structured_extract: StructuredExtractor,
    max_retry: int = 1,
) -> dict[str, Any]:
    """Run structured extraction and source-grounding validation."""
    target = select_eligibility_chunks(chunks)
    body = build_extraction_body(target)
    last_notes = ""

    for attempt in range(max_retry + 1):
        try:
            result = structured_extract(SYSTEM_PROMPT, body, SLOT_SCHEMA)
        except Exception as error:
            return {
                "slots": [],
                "status": "failed",
                "notes": f"구조화 추출 호출 실패: {type(error).__name__}",
                "target_chunk_ids": [chunk.get("chunk_id") for chunk in target],
            }

        accepted: list[dict[str, Any]] = []
        rejected: list[str] = []
        requirements = result.get("requirements", []) if isinstance(result, dict) else []

        for extracted in requirements:
            slot = dict(extracted)
            valid, reason, source_chunk = validate_extracted_slot(slot, target)
            if not valid:
                rejected.append(f"{slot.get('raw', '')[:30]}: {reason}")
                continue
            if source_chunk is not None:
                slot["_source_chunk_id"] = source_chunk.get("chunk_id")
                slot["_source_blocks"] = list(source_chunk.get("source_blocks") or [])
            accepted.append(slot)

        if accepted or not requirements:
            return {
                "slots": accepted,
                "status": "ok",
                "notes": f"검증 탈락 {len(rejected)}건: {rejected}" if rejected else "",
                "target_chunk_ids": [chunk.get("chunk_id") for chunk in target],
            }

        last_notes = f"전 슬롯 검증 탈락(시도 {attempt + 1}): {rejected}"

    return {
        "slots": [],
        "status": "failed",
        "notes": last_notes,
        "target_chunk_ids": [chunk.get("chunk_id") for chunk in target],
    }
