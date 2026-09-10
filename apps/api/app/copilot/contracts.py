"""Product results preserve backend decisions and their provenance."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ..ai.contracts import Evidence, Judgment, JudgmentStatus, QualificationRequirement, RequirementType
from ..ask_back_schemas import QualificationQuestionRead
from ..qualification.rules.judgment import OverallQualificationStatus, ProfileCompleteness


class ProductProvenance(BaseModel):
    case_id: UUID
    notice_id: UUID
    notice_version_id: UUID
    version_number: int
    company_id: UUID
    analysis_run_id: UUID
    judgment_run_id: UUID
    analysis_status: Literal["SUCCEEDED", "PARTIAL"]
    rule_version: str


class RequirementJudgmentSummary(Judgment):
    type: RequirementType
    raw: str


class QualificationSummary(BaseModel):
    provenance: ProductProvenance
    overall_status: OverallQualificationStatus
    analysis_status: Literal["SUCCEEDED", "PARTIAL"]
    judgment_counts: dict[JudgmentStatus, int]
    judgments: list[RequirementJudgmentSummary]


class RequirementEvidenceResult(BaseModel):
    provenance: ProductProvenance
    requirement: QualificationRequirement
    evidence: list[Evidence]


class RequiredChecksResult(BaseModel):
    provenance: ProductProvenance
    questions: list[QualificationQuestionRead]
    user_answer_requires_askable: Literal[True] = Field(
        default=True,
        description="Only askable=true permits a user-answer action; other UNKNOWNs require source review.",
    )


class JudgmentProfileResult(BaseModel):
    provenance: ProductProvenance
    profile_snapshot: dict[str, Any]
    profile_completeness: ProfileCompleteness
