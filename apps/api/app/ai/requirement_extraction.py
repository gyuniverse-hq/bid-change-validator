"""Eligibility requirement extraction over semantic chunks.

This module ports the useful extraction/guardrail behavior from the existing
`bid-change-validator-llm-rag/eligibility/slots.py` PoC without coupling the
backend package to a specific LLM SDK.

The production boundary is:

    backend extracted_blocks
        -> canonical source blocks
        -> semantic chunks
        -> structured extractor (LLM adapter supplied by caller)
        -> validated legacy slots

Numeric normalization and Canonical Requirement conversion remain separate code
steps. This keeps the original rule: LLM extracts source text; code normalizes
and judges.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

StructuredExtractor = Callable[[str, str, dict[str, Any]], dict[str, Any]]

_ELIGIBILITY_KEYWORDS = (
    "참가자격",
    "입찰참가",
    "자격요건",
    "실적",
    "참가 자격",
    "제한사항",
    "신청자격",
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
                        "근거조항": {
                            "type": ["string", "null"],
                            "description": "제공된 텍스트에서 확인되는 조항 번호/라벨",
                        },
                    },
                    "required": ["유형", "raw", "기간_raw", "금액_raw", "근거조항"],
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
4. 근거조항에는 그 요건이 적힌 조항 번호를 담되, 제공된 텍스트에서 확인되는 것만 적는다."""

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


def select_eligibility_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select eligibility sections and their children without crossing documents.

    The original PoC discovered that selecting only the heading chunk hurts
    recall because actual conditions usually live in child clauses (e.g. 3.1,
    3.2). Keep that behavior while operating on the new semantic chunk shape.

    The integration pipeline can analyze several Backend documents in one run.
    A section anchored in document A must never absorb leading chunks from
    document B merely because document B does not start with a top-level heading.
    """
    selected: dict[int, dict[str, Any]] = {}
    for index, chunk in enumerate(chunks):
        text = chunk.get("text") or ""
        if not any(keyword in text for keyword in _ELIGIBILITY_KEYWORDS):
            continue

        selected[index] = chunk
        if not _is_top_level(chunk):
            continue

        anchor_document_id = _chunk_document_id(chunk)
        for child_index in range(index + 1, len(chunks)):
            candidate = chunks[child_index]
            candidate_document_id = _chunk_document_id(candidate)

            if (
                anchor_document_id is not None
                and candidate_document_id is not None
                and candidate_document_id != anchor_document_id
            ):
                break

            candidate_text = candidate.get("text") or ""
            if _is_top_level(candidate) and not any(
                keyword in candidate_text for keyword in _ELIGIBILITY_KEYWORDS
            ):
                break
            selected[child_index] = candidate

    if selected:
        return [selected[index] for index in sorted(selected)]
    return chunks[:8]


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _normalize_reference(value: str) -> str:
    return re.sub(r"^(?:조항|제)\s*", "", value.strip()).rstrip(".)조항 ")


def _find_source_chunk(raw: str, chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    probe = _squash(raw)
    if not probe:
        return None
    # The existing guardrail compares a short prefix to tolerate extraction
    # formatting differences while still requiring source-grounded text.
    prefix = probe[:40]
    for chunk in chunks:
        if prefix in _squash(chunk.get("text") or ""):
            return chunk
    return None


def validate_extracted_slot(
    slot: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> tuple[bool, str, dict[str, Any] | None]:
    """Reject unsupported raw text or a hallucinated clause reference."""
    raw = (slot.get("raw") or "").strip()
    if not raw:
        return False, "raw 비어 있음", None

    source_chunk = _find_source_chunk(raw, chunks)
    if source_chunk is None:
        return False, "raw가 본문에 존재하지 않음(과잉 추출 의심)", None

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
    """Run structured extraction and source-grounding validation.

    The caller supplies the model adapter. That lets this integration package be
    tested without OpenAI/network access and avoids changing the backend team's
    dependency/configuration files before the interface is agreed.

    Validated slots receive private integration metadata (`_source_chunk_id`,
    `_source_blocks`) so the next Evidence adapter can build a canonical citation
    without searching the source again.
    """
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
