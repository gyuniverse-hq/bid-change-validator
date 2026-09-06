"""Orchestration for qualification requirement analysis.

This module keeps the integration boundary inside `app.ai` and composes the
pieces already introduced on the integration branch:

    backend document blocks
        -> canonical source blocks
        -> semantic chunks
        -> structured extraction
        -> optional deterministic value normalization
        -> canonical Requirement + Evidence
        -> RequirementAnalysisResult

The caller still supplies the structured LLM extractor and numeric normalizer so
we do not modify backend dependency/configuration files before the team agrees on
the runtime wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .analysis_result import RequirementAnalysisResult, build_requirement_analysis_result
from .backend_blocks import canonical_source_blocks
from .canonicalize import canonicalize_validated_slots
from .chunking import chunk_source_blocks
from .requirement_extraction import StructuredExtractor, extract_legacy_slots

ValueNormalizer = Callable[[str], dict[str, Any]]


class QualificationDocumentInput(BaseModel):
    """Minimal Backend -> AI document input used by the orchestration layer.

    `document_id` and the extracted block payload are Backend-owned. The AI layer
    does not infer or create document identity.
    """

    document_id: str
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
    """Chunk each document independently, then assign run-global chunk IDs.

    Documents must never be merged into one semantic chunk. Besides being
    semantically unsafe, Evidence requires exactly one Backend document_id.
    """
    chunks: list[dict[str, Any]] = []

    for document in documents:
        source_blocks = canonical_source_blocks(
            document_id=document.document_id,
            text_sha256=document.extracted_text_sha256,
            blocks=document.extracted_blocks,
        )
        document_chunks = chunk_source_blocks(source_blocks, max_chars=max_chunk_chars)

        for chunk in document_chunks:
            chunks.append(
                {
                    **chunk,
                    "chunk_id": f"CHUNK-{len(chunks):04d}",
                }
            )

    return chunks


def _normalize_extracted_slots(
    slots: list[dict[str, Any]],
    *,
    normalize_value: ValueNormalizer | None,
) -> list[dict[str, Any]]:
    """Apply code-only normalization to raw amount/period fields when supplied.

    The structured extractor must only return source strings. This helper mirrors
    the old LLM/RAG PoC boundary while keeping the concrete normalizer injectable
    until it is ported into this package.
    """
    normalized_slots: list[dict[str, Any]] = []

    for source_slot in slots:
        slot = dict(source_slot)
        if normalize_value is not None:
            amount_raw = slot.get("금액_raw")
            period_raw = slot.get("기간_raw")
            if amount_raw:
                slot["금액_norm"] = normalize_value(str(amount_raw))
            if period_raw:
                slot["기간_norm"] = normalize_value(str(period_raw))
        normalized_slots.append(slot)

    return normalized_slots


def analyze_qualification_documents(
    analysis_input: QualificationAnalysisInput,
    *,
    structured_extract: StructuredExtractor,
    normalize_value: ValueNormalizer | None = None,
    max_retry: int = 1,
    max_chunk_chars: int = 1800,
) -> RequirementAnalysisResult:
    """Run one qualification Requirement analysis without touching Backend state.

    This function is intentionally pure from the Backend perspective: it receives
    already-extracted document blocks and returns a validated contract object. It
    performs no DB writes, no file parsing, and no router/service mutation.
    """
    document_ids = [document.document_id for document in analysis_input.documents]
    chunks = _build_global_chunks(
        analysis_input.documents,
        max_chunk_chars=max_chunk_chars,
    )

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
        target_chunk_ids=list(extraction.get("target_chunk_ids") or []),
    )
