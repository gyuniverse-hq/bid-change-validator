"""Backend-facing qualification analysis contract. Source IDs remain backend-owned."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator, model_serializer
from ...contracts import Evidence, QualificationRequirement

AnalysisStatus = Literal["SUCCEEDED", "PARTIAL", "FAILED"]
AnalysisKind = Literal["QUALIFICATION_REQUIREMENTS"]
DiagnosticSeverity = Literal["INFO", "WARNING", "ERROR"]
DroppedReasonCode = Literal["MISSING_RAW", "RAW_NOT_FOUND_IN_SOURCE", "DETAIL_NOT_FOUND_IN_SOURCE", "SOURCE_VALIDATION_FAILED"]
DiagnosticKind = Literal["PIPELINE", "NOTICE_FACT"]


class AnalysisDiagnostic(BaseModel):
    code: str
    severity: DiagnosticSeverity = "WARNING"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    kind: DiagnosticKind = "PIPELINE"
    evidence_keys: list[str] = Field(default_factory=list)


class DroppedRequirement(BaseModel):
    raw: str
    reason_code: DroppedReasonCode
    detail_field: str | None = None
    detail_value: str | None = None
    validation_code: str | None = None

    @model_serializer(mode="wrap")
    def optional_detail_fields(self, handler):
        result = handler(self)
        return {key: value for key, value in result.items()
                if key not in {"detail_field", "detail_value", "validation_code"} or value is not None}


class RequirementAnalysisResult(BaseModel):
    contract_version: Literal["ai-analysis-v0.2"] = "ai-analysis-v0.2"
    analysis_kind: AnalysisKind = "QUALIFICATION_REQUIREMENTS"
    status: AnalysisStatus
    notice_id: str
    notice_version_id: str
    document_ids: list[str] = Field(default_factory=list)
    target_chunk_ids: list[str] = Field(default_factory=list)
    requirements: list[QualificationRequirement] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    diagnostics: list[AnalysisDiagnostic] = Field(default_factory=list)
    dropped_requirements: list[DroppedRequirement] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_internal_links(self) -> "RequirementAnalysisResult":
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("document_ids must be unique")
        reqkeys = [r.requirement_key for r in self.requirements]
        if len(reqkeys) != len(set(reqkeys)):
            raise ValueError("requirement_key values must be unique")
        evkeys = [e.evidence_key for e in self.evidence]
        if len(evkeys) != len(set(evkeys)):
            raise ValueError("evidence_key values must be unique")
        for req in self.requirements:
            if req.notice_version_id != self.notice_version_id:
                raise ValueError("requirement notice_version_id must match analysis notice_version_id")
            unresolved = set(req.evidence_keys) - set(evkeys)
            if unresolved:
                raise ValueError(f"requirement contains unresolved evidence keys: {sorted(unresolved)}")
        for item in self.evidence:
            if item.notice_version_id != self.notice_version_id:
                raise ValueError("evidence notice_version_id must match analysis notice_version_id")
            if item.document_id not in set(self.document_ids):
                raise ValueError(f"evidence document_id is outside analysis scope: {item.document_id}")
        if self.status == "FAILED" and (self.requirements or self.evidence):
            raise ValueError("FAILED analysis must not expose canonical results")
        return self


_DIAGNOSTIC_MESSAGES = {
    "PROCEDURAL_REQUIREMENT_REVIEW": "등록 절차를 회사 인증 판정과 분리했습니다. 절차 이행 여부는 별도 확인이 필요합니다.",
    "DUPLICATE_REQUIREMENT": "동일 조건을 그룹 연결과 양쪽 근거를 보존하며 정리했습니다.",
    "INDUSTRY_ALIAS_RESOLVED": "원문의 단일 업종명·코드 연결을 확인해 업종 조건으로 정리했습니다.",
    "UNMAPPED_REQUIREMENT": "공고에서 확인했으나 회사 프로필과 대조할 자격요건이 아닙니다. 판정하지 않고 근거와 함께 기록합니다.",
    "UNMAPPED_PERFORMANCE": "실적요건을 판정 가능한 원자 조건으로 구조화하지 못했습니다.",
    "UNMAPPED_EXPERIENCE_FIELD": "경험분야 요건의 비교값을 구조화하지 못했습니다.",
    "UNMAPPED_INDUSTRY": "업종 요건의 비교값을 구조화하지 못했습니다.",
    "UNMAPPED_REGION": "지역 요건의 비교값을 구조화하지 못했습니다.",
    "UNMAPPED_STAFF": "인력 요건의 인원 또는 역할을 구조화하지 못했습니다.",
    "UNMAPPED_REGISTRATION_CERTIFICATION": "등록·면허·인증 요건의 명칭을 구조화하지 못했습니다.",
    "UNMAPPED_COMPANY_SIZE": "기업규모 요건의 비교값을 구조화하지 못했습니다.",
    "UNKNOWN_LEGACY_TYPE": "지원하지 않는 슬롯 유형이라 판정하지 않고 근거와 함께 기록합니다.",
}
_INFO_PIPELINE_CODES = {"DUPLICATE_REQUIREMENT", "INDUSTRY_ALIAS_RESOLVED"}
_NOTICE_FACT_CODES = {"UNMAPPED_REQUIREMENT", "UNKNOWN_LEGACY_TYPE"}


def _canonical_diagnostic(raw: dict[str, Any]) -> AnalysisDiagnostic:
    code = str(raw.get("code") or "CANONICALIZATION_WARNING")
    fact = code in _NOTICE_FACT_CODES
    return AnalysisDiagnostic(code=code, severity="INFO" if fact or code in _INFO_PIPELINE_CODES else "WARNING",
        message=_DIAGNOSTIC_MESSAGES.get(code, "Canonical 변환 과정에서 확인이 필요합니다."),
        details={key: value for key, value in raw.items() if key not in ("code", "evidence_keys")},
        kind="NOTICE_FACT" if fact else "PIPELINE", evidence_keys=list(raw.get("evidence_keys") or []))


def build_requirement_analysis_result(*, notice_id: str, notice_version_id: str, document_ids: list[str],
    canonicalized: dict[str, Any], extraction_status: str = "ok", extraction_notes: str = "",
    extraction_dropped_requirements: list[dict[str, str]] | None = None, target_chunk_ids: list[str] | None = None,
) -> RequirementAnalysisResult:
    requirements = list(canonicalized.get("requirements") or [])
    evidence = list(canonicalized.get("evidence") or [])
    diagnostics = [_canonical_diagnostic(d) for d in list(canonicalized.get("diagnostics") or [])]
    if extraction_status != "ok":
        diagnostics.insert(0, AnalysisDiagnostic(
            code="EXTRACTION_PARTIAL" if extraction_status == "partial" else "EXTRACTION_FAILED",
            severity="WARNING" if extraction_status == "partial" else "ERROR",
            message="구조화 Requirement 추출 단계가 완료되지 않았습니다.",
            details={"status": extraction_status, "notes": extraction_notes}))
        status: AnalysisStatus = "PARTIAL" if requirements or evidence else "FAILED"
    elif any(item.kind == "PIPELINE" and item.severity != "INFO" for item in diagnostics):
        status = "PARTIAL"
    else:
        status = "SUCCEEDED"
    if extraction_status == "ok" and extraction_notes:
        diagnostics.append(AnalysisDiagnostic(code="EXTRACTION_NOTES", severity="INFO",
            message="Requirement 추출 단계에 추가 검증 메모가 있습니다.", details={"notes": extraction_notes}))
    if status == "FAILED":
        requirements, evidence = [], []
    return RequirementAnalysisResult(status=status, notice_id=notice_id, notice_version_id=notice_version_id,
        document_ids=document_ids, target_chunk_ids=list(target_chunk_ids or []), requirements=requirements,
        evidence=evidence, diagnostics=diagnostics, dropped_requirements=list(extraction_dropped_requirements or []))
