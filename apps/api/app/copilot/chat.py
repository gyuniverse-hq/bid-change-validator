"""Stateless V0: deterministic product routing, opt-in document RAG, no writes."""

import os
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from ..ai.contracts import Evidence
from ..document_rag.answer import GroundedCitation
from ..document_rag.retrieval import retrieve
from ..document_rag.service import load_or_build_version_index
from ..document_rag.store import create_openai_embeddings
from ..models import PreflightCase
from ..qualification.judgment import QualificationJudgmentError
from .actions import ChangedNoticeResult, get_changed_notice, propose_answer
from .contracts import (
    ActionInput, ActionProposal, JudgmentProfileResult, QualificationSummary,
    RequiredChecksResult, RequirementEvidenceResult, RevalidationProposal,
)
from .product_tools import (
    get_judgment_profile_snapshot, get_qualification_summary, get_required_checks,
    get_requirement_evidence,
)

Intent = Literal["QUALIFICATION_SUMMARY", "REQUIREMENT_EVIDENCE", "REQUIRED_CHECKS",
                 "PROFILE_SNAPSHOT", "DOCUMENT_QA", "ACTION_REQUEST", "CHANGED_NOTICE", "UNKNOWN"]


class CopilotChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    requirement_key: str | None = Field(default=None, min_length=1, max_length=200)
    # Explicit UI intent is optional; it selects a read tool, never an eligibility value.
    intent: Intent | None = None
    user_input: ActionInput | None = None
    public_document_question: str | None = Field(default=None, min_length=1, max_length=2000)
    allow_external_processing: StrictBool = False


class ProductSource(BaseModel):
    source_origin: Literal["PRODUCT_EVIDENCE"] = "PRODUCT_EVIDENCE"
    ref: str
    evidence: Evidence


class DocumentSource(GroundedCitation):
    source_origin: Literal["DOCUMENT_RAG"] = "DOCUMENT_RAG"


Source = Annotated[ProductSource | DocumentSource, Field(discriminator="source_origin")]


class CopilotChatResponse(BaseModel):
    answer: str
    intent: Intent
    product_state: QualificationSummary | RequirementEvidenceResult | RequiredChecksResult | JudgmentProfileResult | ChangedNoticeResult | None = None
    citations: list[Source] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    actions: list[ActionProposal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    external_processing_used: bool = False
    external_processing_scope: Literal["PUBLIC_NOTICE_DOCUMENT"] | None = None


def route_intent(request: CopilotChatRequest) -> Intent:
    text = request.message.replace(" ", "")
    # Product truth wins over document routing, including explicit DOCUMENT_QA hints.
    if any(term in text for term in ("참여가능", "참가가능", "참여불가", "참가불가", "판정결과")):
        return "QUALIFICATION_SUMMARY"
    if any(term in text for term in ("근거", "원문", "어디")) and request.requirement_key:
        return "REQUIREMENT_EVIDENCE"
    if request.intent:
        return request.intent
    if request.user_input is not None or any(term in text for term in ("적용해", "재검증해")):
        return "ACTION_REQUEST"
    if any(term in text for term in ("변경공고", "뭐바뀌", "변경된요건")):
        return "CHANGED_NOTICE"
    if any(term in text for term in ("확인", "부족", "입력", "왜")):
        return "REQUIRED_CHECKS"
    if any(term in text for term in ("프로필", "회사정보", "판정당시")):
        return "PROFILE_SNAPSHOT"
    if request.public_document_question or any(term in text for term in ("공고문", "문서", "근거", "원문")):
        return "DOCUMENT_QA"
    # ponytail: bounded Korean keyword routing; add intent evaluation before a classifier.
    return "UNKNOWN"


def chat(db: Session, request: CopilotChatRequest) -> CopilotChatResponse:
    with db.no_autoflush:
        return _chat(db, request)


def _chat(db: Session, request: CopilotChatRequest) -> CopilotChatResponse:
    case = db.get(PreflightCase, request.case_id)
    if case is None:
        raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "검토 건이 없습니다.", status_code=404)
    intent = route_intent(request)
    result = CopilotChatResponse(intent=intent, answer="질문의 요건 또는 요청 종류를 지정해 주세요.")
    if intent == "QUALIFICATION_SUMMARY":
        summary = get_qualification_summary(db, case.id)
        result.product_state = summary
        label = {"eligible": "참가 가능", "ineligible": "참가 불가", "insufficient_data": "확인 필요"}
        result.answer = f"저장된 판정: {label[summary.overall_status]} (분석 상태: {summary.analysis_status})."
    elif intent == "REQUIRED_CHECKS":
        checks = get_required_checks(db, case.id)
        result.product_state = checks
        result.answer = "\n".join(f"{q.requirement_key}: {q.question}"
                                  + ("" if q.askable else " (사용자 답변 적용 불가: 원문 검토 필요)")
                                  for q in checks.questions) or "저장된 판정에 UNKNOWN 요건이 없습니다."
    elif intent == "PROFILE_SNAPSHOT":
        result.product_state = get_judgment_profile_snapshot(db, case.id)
        result.answer = "판정 당시 저장된 회사 정보입니다. 현재 프로필과 다를 수 있습니다."
    elif intent == "REQUIREMENT_EVIDENCE":
        if request.requirement_key:
            evidence = get_requirement_evidence(db, case.id, request.requirement_key)
            result.product_state = evidence
            result.sources = [ProductSource(ref=f"S{i}", evidence=e) for i, e in enumerate(evidence.evidence, 1)]
            result.citations = list(result.sources)
            result.answer = "\n".join(f"{s.evidence.quote} [{s.ref}]" for s in result.sources) or "이 요건에 연결된 원문 근거가 없습니다."
    elif intent == "CHANGED_NOTICE" or (intent == "ACTION_REQUEST" and request.user_input is None):
        if intent == "ACTION_REQUEST" and "재검증" not in request.message:
            result.answer = "적용할 요건과 명시적인 사용자 답변을 먼저 입력해 주세요."
            return result
        changes = get_changed_notice(db, case.id)
        result.product_state = changes
        result.actions = [RevalidationProposal(expected=changes.provenance)]
        result.answer = "\n".join(f"{c.current_key or c.baseline_key}: {c.change_type}" for c in changes.changes)
        result.warnings = ["변경 내역이며 새 참가자격 판정이 아닙니다. 재검증은 별도 확인 후 실행됩니다."]
    elif intent == "ACTION_REQUEST":
        if request.requirement_key and request.user_input is not None:
            result.actions = [propose_answer(db, case.id, request.requirement_key, request.user_input)]
            result.answer = "답변 적용 제안입니다. 아직 저장하지 않았습니다. 내용을 확인해 주세요."
    elif intent == "DOCUMENT_QA":
        if not request.public_document_question or not request.allow_external_processing:
            result.answer = "공개 공고문 질문을 별도로 입력하고 외부 처리에 명시적으로 동의해 주세요."
            return result
        # Never pass message, profile or user_input to embeddings/the answer model.
        question = request.public_document_question
        if route_intent(CopilotChatRequest(case_id=case.id, message=question)) == "QUALIFICATION_SUMMARY":
            result.answer = "회사 참가자격은 저장된 판정 조회를 사용해 주세요."
            return result
        index = load_or_build_version_index(
            db, notice_version_id=case.current_version_id,
            index_root=os.getenv("DOCUMENT_RAG_INDEX_ROOT", "data/document-rag"),
            embeddings=create_openai_embeddings(),
        )
        if index.notice_version_id != str(case.current_version_id):
            raise ValueError("document index does not match current notice version")
        hits = retrieve(index, question, method="hybrid", k=4, fetch_k=12)
        if any(h.metadata.notice_version_id != str(case.current_version_id) for h in hits):
            raise ValueError("document hits do not match current notice version")
        # Copilot V0 exposes source text, never an LLM-generated eligibility claim.
        # The standalone Stage 5 grounded-answer implementation remains available.
        result.sources = [DocumentSource(
            ref=f"S{i}", document_id=h.metadata.document_id, document_name=h.metadata.document_name,
            notice_version_id=h.metadata.notice_version_id, chunk_id=h.metadata.chunk_id,
            clause_label=h.metadata.clause_label, page=h.metadata.page,
            source_locations=list(h.metadata.source_locations), quote=h.text,
        ) for i, h in enumerate(hits, 1)]
        result.citations = list(result.sources)
        lines = []
        for source in result.sources:
            location = ", ".join(source.source_locations) or (
                f"p.{source.page}" if source.page is not None else "위치 정보 없음"
            )
            lines.append(f"[{source.ref}] {source.document_name}; clause={source.clause_label or '정보 없음'}; location={location}")
        result.answer = (f"검색된 공고문 원문 {len(lines)}건입니다. 원문 근거를 확인해 주세요.\n" + "\n".join(lines)
                         if lines else "검색된 공고문 근거가 없습니다.")
        result.external_processing_used = True
        result.external_processing_scope = "PUBLIC_NOTICE_DOCUMENT"
        result.warnings = ["검색된 원문이며 질문의 답이나 참가자격 판정이 아닙니다. 회사 참가자격은 저장된 판정에서 확인해야 합니다."]
    return result
