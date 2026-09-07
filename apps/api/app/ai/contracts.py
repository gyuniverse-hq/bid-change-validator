"""Canonical AI contracts shared by backend and LLM/RAG integration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RequirementType = Literal[
    "PERFORMANCE_AMOUNT",
    "PERFORMANCE_COUNT",
    "INDUSTRY",
    "REGION",
    "STAFF",
    "REGISTRATION_CERTIFICATION",
    "EXPERIENCE_FIELD",
    "COMPANY_SIZE",
]
RequirementOperator = Literal[">=", ">", "<=", "<", "=", "MATCH", "RANGE"]

JudgmentStatus = Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"]
BasisType = Literal["PROFILE", "USER_ANSWER", "NONE"]
ReasonCode = Literal[
    "RULE_MATCH",
    "RULE_MISMATCH",
    "INSUFFICIENT_DATA",
    "NEEDS_REVIEW",
    "UNSUPPORTED_REQUIREMENT",
]
EvidenceSourceType = Literal["NOTICE_DOCUMENT", "PROPOSAL_DOCUMENT"]


class EvidenceLocation(BaseModel):
    # Backend extracted_blocks are the source-of-truth locator. The range fields
    # let one semantic citation cover one or more adjacent source blocks without
    # inventing a PDF page for HWP/HWPX documents.
    block_start: int | None = None
    block_end: int | None = None
    page: int | None = None
    section_index: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    source_line_start: int | None = None
    source_line_end: int | None = None
    clause_label: str | None = None
    display: str | None = None


class Evidence(BaseModel):
    evidence_key: str
    source_type: EvidenceSourceType
    document_id: str
    notice_version_id: str | None = None
    case_id: str | None = None
    chunk_id: str | None = None
    location: EvidenceLocation
    quote: str
    # Original file identity and the exact extracted-text identity are kept
    # separately so an evaluation run stays reproducible even if parsers evolve.
    source_sha256: str | None = None
    extracted_text_sha256: str | None = None


class QualificationRequirement(BaseModel):
    requirement_key: str
    requirement_group_key: str | None = None
    group_operator: Literal["ALL_OF", "ANY_OF"] | None = None
    notice_version_id: str
    type: RequirementType
    operator: RequirementOperator | None = None
    value: int | float | str | None = None
    unit: str | None = None
    period_months: float | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    raw: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_keys: list[str] = Field(default_factory=list)


class Judgment(BaseModel):
    judgment_key: str
    preflight_case_id: str
    notice_version_id: str
    requirement_key: str
    status: JudgmentStatus
    basis_type: BasisType
    evidence_held: bool = False
    reason_code: ReasonCode
    requires_evidence: bool = False
    profile_refs: list[dict[str, str]] = Field(default_factory=list)
    requirement_evidence_keys: list[str] = Field(default_factory=list)
    rule_version: str | None = None
