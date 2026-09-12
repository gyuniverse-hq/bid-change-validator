"""Additive Copilot endpoints. Chat never calls action execution."""

from fastapi import APIRouter, Depends, Header
from openai import OpenAIError
from sqlalchemy.orm import Session

from ..ask_back_schemas import QualificationAnswerRead
from ..database import get_db
from ..errors import ApiError
from ..qualification.judgment import QualificationJudgmentError
from ..revalidation_schemas import QualificationRevalidationRead
from .actions import confirm_action
from .chat import CopilotChatRequest, CopilotChatResponse, chat, route_intent
from .context import compact
from .contracts import ConfirmAction
from .document_qa import answer_grounded_document_question
from .intent_resolver import ResolvedIntent, resolve_intent
from .semantic_router import SemanticRouter

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


def semantic_recheck_candidate(payload: CopilotChatRequest, deterministic: str) -> bool:
    """Return True only for weak free-text deterministic reads.

    E2 must not override an explicit UI route, a payload-backed write, or a clear
    deterministic command. It may however re-check keyword-heavy read matches
    that are known to produce false positives, such as `확인서` being mistaken for
    REQUIRED_CHECKS or `어떻게 적용되는지 설명` being mistaken for a write.
    """
    if payload.intent is not None and payload.intent != "UNKNOWN":
        return False
    if payload.user_input is not None:
        return False
    if deterministic == "UNKNOWN":
        return True
    if deterministic == "REQUIRED_CHECKS":
        return True
    if deterministic == "ACTION_REQUEST":
        text = compact(payload.message)
        passive_application_read = "적용되" in text and any(
            word in text for word in ("설명", "어떻게", "의미", "조건", "예외", "원문")
        )
        return passive_application_read
    return False


def resolve_chat_payload(
    payload: CopilotChatRequest,
    *,
    semantic_processing: bool,
    classifier=None,
) -> tuple[CopilotChatRequest, ResolvedIntent]:
    """Resolve a chat route while preserving explicit/write safety boundaries.

    Without semantic opt-in the deterministic result is unchanged. With opt-in,
    E2 fills UNKNOWN reads and may re-check only the weak deterministic read
    matches identified by `semantic_recheck_candidate`. If semantic routing is
    unavailable, low-confidence, UNKNOWN, or attempts ACTION_REQUEST escalation,
    a previously known deterministic result is restored.
    """
    deterministic = route_intent(payload)
    semantic_classifier = classifier
    if semantic_processing and semantic_classifier is None:
        semantic_classifier = SemanticRouter()

    recheck = semantic_processing and semantic_recheck_candidate(payload, deterministic)
    resolver_input = "UNKNOWN" if recheck else deterministic
    context = payload.conversation_context
    resolved = resolve_intent(
        deterministic_intent=resolver_input,
        message=payload.message,
        classifier=semantic_classifier if semantic_processing else None,
        explicit_intent=payload.intent,
        has_user_input=payload.user_input is not None,
        last_intent=context.last_response_intent if context else None,
        visible_targets=context.visible_requirement_keys if context else None,
    )

    # A weak deterministic read is only replaced by a trusted semantic read.
    # Provider failure / UNKNOWN / blocked action escalation falls back to the
    # original deterministic behavior rather than degrading an existing route.
    if recheck and deterministic != "UNKNOWN" and resolved.route_source == "FALLBACK":
        resolved = ResolvedIntent(
            intent=deterministic,
            route_source="DETERMINISTIC",
            semantic=resolved.semantic,
        )

    if resolved.route_source == "SEMANTIC":
        payload = payload.model_copy(update={"intent": resolved.intent})
    return payload, resolved


@router.post("/chat", response_model=CopilotChatResponse)
def copilot_chat(
    payload: CopilotChatRequest,
    db: Session = Depends(get_db),
    semantic_processing: bool = Header(False, alias="X-Copilot-Semantic-Processing"),
):
    try:
        payload, _ = resolve_chat_payload(
            payload,
            semantic_processing=semantic_processing,
        )
        if route_intent(payload) == "DOCUMENT_QA":
            return answer_grounded_document_question(db, payload)
        return chat(db, payload)
    except QualificationJudgmentError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except (ValueError, RuntimeError, OpenAIError) as error:
        raise ApiError(502, "DOCUMENT_QA_FAILED", "문서 근거 응답을 안전하게 생성하지 못했습니다.") from error


@router.post("/actions/confirm", response_model=QualificationAnswerRead | QualificationRevalidationRead)
def copilot_confirm(payload: ConfirmAction, db: Session = Depends(get_db)):
    try:
        return confirm_action(db, payload)
    except QualificationJudgmentError as error:
        db.rollback()
        raise ApiError(error.status_code, error.code, error.message) from error
