"""Versioned conversation contracts; server facts and generated claims stay separate."""
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import ActionProposal, ProductProvenance


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Scope(Contract):
    case_id: UUID
    company_id: UUID | None
    notice_id: UUID
    notice_version_id: UUID
    analysis_run_id: UUID | None = None
    judgment_run_id: UUID | None = None


class Fact(Contract):
    fact_id: str
    kind: Literal['SERVER_RESULT', 'NOTICE_FACT', 'PROFILE_FACT', 'USER_ASSERTION', 'ASSUMPTION']
    text: str
    source_ids: list[str] = Field(default_factory=list)
    requirement_key: str | None = None
    target_kind: Literal['REQUIREMENT', 'MANUAL', 'DOCUMENT', 'CHANGE', 'ASSUMPTION'] = 'DOCUMENT'
    origin_tool: Literal['READ_JUDGMENT', 'READ_PROFILE', 'READ_CHECKS', 'READ_DOCUMENT', 'READ_CHANGES', 'PROPOSE_ACTION', 'ACKNOWLEDGE_ACTION'] | None = None
    entity_ref: str | None = None
    scope: Scope


class Source(Contract):
    source_id: str
    kind: Literal['DOCUMENT', 'PRODUCT', 'TURN', 'PROCEDURE']
    quote: str
    scope: Scope
    document_id: str | None = None
    location: dict[str, Any] = Field(default_factory=dict)
    source_sha256: str | None = None
    extracted_sha256: str | None = None


class Task(Contract):
    kind: Literal['READ_JUDGMENT', 'READ_PROFILE', 'READ_CHECKS', 'READ_DOCUMENT', 'READ_CHANGES', 'REVIEW_ASSUMPTION', 'PROPOSE_ACTION', 'ACKNOWLEDGE_ACTION']
    question: str = Field(max_length=4000)
    scope_ref: Literal['current_case'] = 'current_case'
    requirement_id: str | None = None


class TaskPlan(Contract):
    goal: str = Field(max_length=4000)
    tasks: list[Task] = Field(min_length=1, max_length=6)
    clarification: str | None = None
    resume_unresolved: bool = False


class JobRequirement(Contract):
    requirement_id: str
    request: str
    tool: str
    status: Literal['OPEN', 'ANSWERED', 'AWAITING_CONFIRMATION', 'EXECUTED', 'UNAVAILABLE', 'STALE'] = 'OPEN'
    basis: Scope
    fingerprints: dict[str, str] = Field(default_factory=dict)
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    last_turn_id: str | None = None
    reason: str = ''
    remaining: list[str] = Field(default_factory=list)
    action_keys: list[str] = Field(default_factory=list)
    execution_result_ids: list[str] = Field(default_factory=list)


class JobState(Contract):
    job_id: UUID
    goal: str
    requirements: list[JobRequirement] = Field(default_factory=list)
    status: Literal['OPEN', 'COMPLETE'] = 'OPEN'
    revision: int = 0
    remaining: list[str] = Field(default_factory=list)


class EvidenceBundle(Contract):
    scope: Scope
    server_context: dict[str, Any] = Field(default_factory=dict)
    facts: list[Fact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    coverage: dict[str, str] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    capabilities: dict[str, int] = Field(default_factory=dict)
    fingerprints: dict[str, str] = Field(default_factory=dict)


class Claim(Contract):
    claim_id: str
    text: str = Field(min_length=1, max_length=3000)
    fact_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    validation: Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT', 'UNCHECKED'] = 'UNCHECKED'
    method: Literal['rule', 'extractive', 'semantic'] = 'semantic'
    reason: str = ''
    speech_act: Literal['ASSERTION', 'CHECK_REQUEST', 'ASSUMPTION'] = 'ASSERTION'


class DraftClaim(Contract):
    claim_id: str
    text: str = Field(min_length=1, max_length=3000)
    fact_ids: list[str]
    source_ids: list[str]
    speech_act: Literal['ASSERTION', 'CHECK_REQUEST', 'ASSUMPTION'] = 'ASSERTION'


class Draft(Contract):
    claims: list[DraftClaim] = Field(max_length=60)


class FactCitedClaim(Contract):
    claim_id: str
    text: str = Field(min_length=1, max_length=3000)
    fact_ids: list[str]
    speech_act: Literal['ASSERTION', 'CHECK_REQUEST', 'ASSUMPTION'] = 'ASSERTION'


class FactCitedDraft(Contract):
    claims: list[FactCitedClaim] = Field(max_length=60)


class CandidateClaim(DraftClaim):
    """Internal validation record; invalid references never enter AnswerEnvelope."""
    validation: Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT', 'UNCHECKED'] = 'UNCHECKED'
    method: Literal['semantic'] = 'semantic'
    reason: str = ''


class ClaimVerdict(Contract):
    claim_id: str
    status: Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT']
    reason: str
    observed_act: Literal['ASSERTION', 'CHECK_REQUEST', 'ASSUMPTION'] = 'ASSERTION'


class AcceptanceCriterion(Contract):
    model_config = ConfigDict(extra='forbid', frozen=True)
    criterion_id: str
    task_kind: str
    mode: Literal['CHECKLIST', 'PROFILE_SUMMARY', 'EXPLANATION']
    requirement: str
    fact_ids: tuple[str, ...]


class CriterionVerdict(Contract):
    criterion_id: str
    status: Literal['MET', 'MISSING', 'UNAVAILABLE']
    claim_ids: list[str]
    reason: str


class Verdicts(Contract):
    verdicts: list[ClaimVerdict]
    task_coverage: Literal['COMPLETE', 'PARTIAL', 'UNKNOWN'] = 'UNKNOWN'
    missing_topics: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[CriterionVerdict] = Field(default_factory=list)


class Target(Contract):
    target_id: str
    kind: str
    label: str
    message_id: str
    ordinal: int
    fact_ids: list[str]
    source_ids: list[str]
    requirement_key: str | None = None
    origin_tool: Literal['READ_JUDGMENT', 'READ_PROFILE', 'READ_CHECKS', 'READ_DOCUMENT', 'READ_CHANGES'] | None = None
    entity_ref: str | None = None


class StatusCard(Contract):
    status: str
    text: str
    provenance: ProductProvenance


class Processing(Contract):
    path: Literal['v3.1'] = 'v3.1'
    model: str | None = None
    fallback: bool = False
    task_status: Literal['PASS', 'PARTIAL', 'FAIL'] = 'PARTIAL'
    elapsed_ms: int = 0
    calls: list[dict[str, Any]] = Field(default_factory=list)
    validation_events: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)
    deadline_seconds: int = 45
    storage: str = 'process-memory; restart clears history; one worker only'


class AnswerEnvelope(Contract):
    version: Literal['3.1'] = '3.1'
    conversation_id: UUID
    context_revision: int
    message_id: str
    status_card: StatusCard | None = None
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    follow_up_targets: list[Target] = Field(default_factory=list)
    actions: list[ActionProposal] = Field(default_factory=list)
    capabilities: dict[str, int] = Field(default_factory=dict)
    clarification: str | None = None
    processing: Processing = Field(default_factory=Processing)
    job: JobState | None = None

    @field_validator('claims')
    @classmethod
    def unique_claim_ids(cls, claims):
        if len({c.claim_id for c in claims}) != len(claims):
            raise ValueError('DUPLICATE_CLAIM')
        return claims


class Message(Contract):
    turn_id: str
    question: str
    answer: str
    scope: Scope
    action_proposed: bool = False


class ConversationState(Contract):
    conversation_id: UUID
    owner: str
    scope: Scope
    context_revision: int = 0
    messages: list[Message] = Field(default_factory=list)
    targets: list[Target] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    fingerprints: dict[str, str] = Field(default_factory=dict)
    job: JobState | None = None
    document_reviews: dict[str, dict[str, Any]] = Field(default_factory=dict)
    answer_review: dict[str, Any] = Field(default_factory=dict)
    document_memory: dict[str, Any] = Field(default_factory=dict)
