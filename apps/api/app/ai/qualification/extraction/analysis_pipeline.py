"""Orchestration for qualification requirement analysis.

The structured extractor is injectable. Company facts and Backend persistence
remain outside this module. legacy/review_v1 share the validated canonical path.
"""
from __future__ import annotations
from collections.abc import Callable
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator
from .review_execution import ReviewOptions
from .analysis_result import AnalysisDiagnostic, RequirementAnalysisResult, build_requirement_analysis_result
from .backend_blocks import canonical_source_blocks
from ..canonical.canonicalize import canonicalize_validated_slots
from ..canonical.slot_money import normalize_slot_money, money_normalization_error, failed_money
from .chunking import chunk_source_blocks
from ...normalization import normalize_value as default_normalize_value
from .requirement_extraction import StructuredExtractor, extract_legacy_slots

ValueNormalizer = Callable[[str], dict[str, Any]]


class QualificationDocumentInput(BaseModel):
    document_id: str
    file_sha256: str | None = None
    extracted_text_sha256: str | None = None
    extracted_blocks: list[dict[str, Any]] = Field(default_factory=list)


class QualificationAnalysisInput(BaseModel):
    notice_id: str
    notice_version_id: str
    documents: list[QualificationDocumentInput]

    @model_validator(mode="after")
    def validate_document_ids(self) -> "QualificationAnalysisInput":
        ids = [doc.document_id for doc in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document_id values must be unique inside one analysis input")
        return self


def _build_global_chunks(documents: list[QualificationDocumentInput], *, max_chunk_chars: int) -> list[dict[str, Any]]:
    chunks = []
    for document in documents:
        blocks = canonical_source_blocks(document_id=document.document_id, file_sha256=document.file_sha256,
            text_sha256=document.extracted_text_sha256, blocks=document.extracted_blocks)
        for chunk in chunk_source_blocks(blocks, max_chars=max_chunk_chars):
            chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})
    return chunks


def _normalize_extracted_slots(slots: list[dict[str, Any]], *, normalize_value: ValueNormalizer) -> list[dict[str, Any]]:
    normalized_slots = []
    for source_slot in slots:
        slot = dict(source_slot)
        for raw_field, normalized_field in (("금액_raw", "금액_norm"), ("기간_raw", "기간_norm"), ("인원_raw", "인원_norm")):
            raw_value = slot.get(raw_field)
            if raw_value:
                if raw_field == "금액_raw":
                    normalized = (normalize_slot_money(str(raw_value)) if normalize_value is default_normalize_value
                                  else normalize_value(str(raw_value)))
                    error = money_normalization_error(normalized, str(raw_value))
                    slot[normalized_field] = failed_money(raw_value, error) if error else normalized
                else:
                    slot[normalized_field] = normalize_value(str(raw_value))
        normalized_slots.append(slot)
    return normalized_slots


def analyze_qualification_documents(analysis_input: QualificationAnalysisInput, *,
    structured_extract: StructuredExtractor, normalize_value: ValueNormalizer = default_normalize_value,
    max_retry: int = 1, max_chunk_chars: int = 1800,
    extraction_strategy: Literal["legacy", "review_v1"] = "legacy", review_options: ReviewOptions | None = None,
) -> RequirementAnalysisResult:
    document_ids = [doc.document_id for doc in analysis_input.documents]
    if extraction_strategy not in {"legacy", "review_v1"}:
        raise ValueError("unsupported extraction_strategy")
    if extraction_strategy == "review_v1":
        from .review_extraction import extract_review_slots
        source_blocks = [{**block, "document_id": doc.document_id, "source_sha256": doc.file_sha256,
                          "extracted_text_sha256": doc.extracted_text_sha256}
                         for doc in analysis_input.documents for block in doc.extracted_blocks]
        extraction = extract_review_slots(source_blocks, notice_version_id=analysis_input.notice_version_id,
            structured_extract=structured_extract, options=review_options or ReviewOptions(max_retries=max_retry))
    else:
        if review_options is not None:
            raise ValueError("review_options requires extraction_strategy='review_v1'")
        chunks = _build_global_chunks(analysis_input.documents, max_chunk_chars=max_chunk_chars)
        if not chunks:
            return build_requirement_analysis_result(notice_id=analysis_input.notice_id,
                notice_version_id=analysis_input.notice_version_id, document_ids=document_ids,
                canonicalized={"requirements": [], "evidence": [], "diagnostics": []}, extraction_status="failed",
                extraction_notes="분석 가능한 extracted_blocks가 없습니다.", target_chunk_ids=[])
        extraction = extract_legacy_slots(chunks, structured_extract=structured_extract, max_retry=max_retry)
    normalized_slots = _normalize_extracted_slots(list(extraction.get("slots") or []), normalize_value=normalize_value)
    canonicalized = canonicalize_validated_slots(normalized_slots, notice_version_id=analysis_input.notice_version_id,
                                                source_type="NOTICE_DOCUMENT")
    result = build_requirement_analysis_result(notice_id=analysis_input.notice_id,
        notice_version_id=analysis_input.notice_version_id, document_ids=document_ids, canonicalized=canonicalized,
        extraction_status=str(extraction.get("status") or "failed"), extraction_notes=str(extraction.get("notes") or ""),
        extraction_dropped_requirements=list(extraction.get("dropped_requirements") or []),
        target_chunk_ids=list(extraction.get("target_chunk_ids") or []))
    if extraction_strategy == "review_v1":
        unresolved = [item for item in result.diagnostics if item.code.startswith(("UNMAPPED_", "UNKNOWN_LEGACY_"))]
        diagnostics = [item.model_copy(update={"kind": "PIPELINE", "severity": "WARNING",
            "message": "검토 후보를 판정 가능한 요건으로 구조화하지 못했습니다."}) if item in unresolved else item
            for item in result.diagnostics]
        diagnostics.append(AnalysisDiagnostic(code="REVIEW_EXECUTION_AUDIT", severity="INFO",
            message="후보 처리 내역입니다. COMPLETE는 의미 정확성이나 참가 가능을 보증하지 않습니다.",
            details=extraction["review_audit"]))
        status = "PARTIAL" if unresolved and result.status == "SUCCEEDED" else result.status
        return result.model_copy(update={"diagnostics": diagnostics, "status": status})
    return result
