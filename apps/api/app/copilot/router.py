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
from .contracts import ConfirmAction
from .intent_resolver import ResolvedIntent, resolve_intent
from .semantic_router import SemanticRouter

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


def resolve_chat_payload(
    payload: CopilotChatRequest,
    *,
    semantic_processing: bool,
    classifier=None,
) -> tuple[CopilotChatRequest, ResolvedIntent]:
    """Apply semantic routing only to deterministic UNKNOWN read requests.

    The HTTP header is an explicit consent boundary for sending the user's
    question text to the semantic classifier. Company profile, judgment state and
    user_input are never placed in the semantic prompt by this layer.
    """
    deterministic = route_intent(payload)
    semantic_classifier = classifier
    if semantic_processing and semantic_classifier is None:
        semantic_classifier = SemanticRouter()

    context = payload.conversation_context
    resolved = resolve_intent(
        deterministic_intent=deterministic,
        message=payload.message,
        classifier=semantic_classifier if semantic_processing else None,
        explicit_intent=payload.intent,
        has_user_input=payload.user_input is not None,
        last_intent=context.last_response_intent if context else None,
        visible_targets=context.visible_requirement_keys if context else None,
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
