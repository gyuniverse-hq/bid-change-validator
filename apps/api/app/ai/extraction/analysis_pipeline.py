"""Orchestration for qualification requirement analysis.

This module keeps the integration boundary inside `app.ai` and composes:

    backend document blocks
        -> canonical source blocks
        -> semantic chunks
        -> structured extraction
        -> deterministic value normalization
        -> canonical Requirement + Evidence
        -> RequirementAnalysisResult

The structured LLM extractor remains injectable. Normalization is deterministic;
callers may still override the normalizer in tests or experiments.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .analysis_result import RequirementAnalysisResult, build_requirement_analysis_result
from .backend_blocks import canonical_source_blocks
from .canonicalize import canonicalize_validated_slots
from ..chunking import chunk_source_blocks
from ..normalization import normalize_value as default_normalize_value
from .requirement_extraction import StructuredExtractor, extract_legacy_slots

ValueNormalizer = Callable[[str], dict[str, Any]]


class QualificationDocumentInput(BaseModel):
    """Minimal Backend -> AI document input used by the orchestration layer."""

    document_id: str
    file_sha256: str | None = None
    extracted_text_sha256: str | None = None
    extracted_blocks: list[dict[str, Any]] = Field(default_factory=list)


class QualificationAnalysisInput(BaseModel):
    """Backend-facing input contract for one notice-version analysis run."""

    notice_id: str
    notice_version_id: str
    documents: list[QualificationDocumentInput]

    @model_validator(mode="after")
    def validate_document_ids(self) -> "QualificationAnalysisInput":
        document_ids = [document.document_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("document_id values must be unique inside one analysis input")
        return self


def _build_global_chunks(
    documents: list[QualificationDocumentInput],
    *,
    max_chunk_chars: int,
) -> list[dict[str, Any]]:
    """Chunk each document independently, then assign run-global chunk IDs."""
    chunks: list[dict[str, Any]] = []

    for document in documents:
        source_blocks = canonical_source_blocks(
            document_id=document.document_id,
            file_sha256=document.file_sha256,
            text_sha256=document.extracted_text_sha256,
            blocks=document.extracted_blocks,
        )
        document_chunks = chunk_source_blocks(source_blocks, max_chars=max_chunk_chars)

        for chunk in document_chunks:
            chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})

    return chunks


def _normalize_extracted_slots(
    slots: list[dict[str, Any]],
    *,
    normalize_value: ValueNormalizer,
) -> list[dict[str, Any]]:
    """Apply code-only normalization to numeric operands exposed by extraction."""
    normalized_slots: list[dict[str, Any]] = []

    for source_slot in slots:
        slot = dict(source_slot)
        for raw_field, normalized_field in (
            ("금액_raw", "금액_norm"),
            ("기간_raw", "기간_norm"),
            ("인원_raw", "인원_norm"),
        ):
            raw_value = slot.get(raw_field)
            if raw_value:
                slot[normalized_field] = normalize_value(str(raw_value))
        normalized_slots.append(slot)

    return normalized_slots


def analyze_qualification_documents(
    analysis_input: QualificationAnalysisInput,
    *,
    structured_extract: StructuredExtractor,
    normalize_value: ValueNormalizer = default_normalize_value,
    max_retry: int = 1,
    max_chunk_chars: int = 1800,
) -> RequirementAnalysisResult:
    """Run one qualification Requirement analysis without touching Backend state."""
    document_ids = [document.document_id for document in analysis_input.documents]
    chunks = _build_global_chunks(analysis_input.documents, max_chunk_chars=max_chunk_chars)

    if not chunks:
        return build_requirement_analysis_result(
            notice_id=analysis_input.notice_id,
            notice_version_id=analysis_input.notice_version_id,
            document_ids=document_ids,
            canonicalized={"requirements": [], "evidence": [], "diagnostics": []},
            extraction_status="failed",
            extraction_notes="분석 가능한 extracted_blocks가 없습니다.",
            target_chunk_ids=[],
        )

    extraction = extract_legacy_slots(
        chunks,
        structured_extract=structured_extract,
        max_retry=max_retry,
    )

    normalized_slots = _normalize_extracted_slots(
        list(extraction.get("slots") or []),
        normalize_value=normalize_value,
    )

    canonicalized = canonicalize_validated_slots(
        normalized_slots,
        notice_version_id=analysis_input.notice_version_id,
        source_type="NOTICE_DOCUMENT",
    )

    return build_requirement_analysis_result(
        notice_id=analysis_input.notice_id,
        notice_version_id=analysis_input.notice_version_id,
        document_ids=document_ids,
        canonicalized=canonicalized,
        extraction_status=str(extraction.get("status") or "failed"),
        extraction_notes=str(extraction.get("notes") or ""),
        extraction_dropped_requirements=list(
            extraction.get("dropped_requirements") or []
        ),
        target_chunk_ids=list(extraction.get("target_chunk_ids") or []),
    )
