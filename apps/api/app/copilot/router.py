"""Additive Copilot endpoints. Chat never calls action execution."""

from fastapi import APIRouter, Depends
from openai import OpenAIError
from sqlalchemy.orm import Session

from ..auth import authorize_case_access, get_optional_current_user
from ..auth_models import AppUser
from ..ask_back_schemas import QualificationAnswerRead
from ..database import get_db
from ..errors import ApiError
from ..qualification.judgment import QualificationJudgmentError
from ..revalidation_schemas import QualificationRevalidationRead
from .actions import confirm_action
from .chat import CopilotChatRequest, CopilotChatResponse, chat
from .contracts import ConfirmAction

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.post("/chat", response_model=CopilotChatResponse)
def copilot_chat(
    payload: CopilotChatRequest,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
):
    authorize_case_access(db, user, payload.case_id)
    try:
        return chat(db, payload)
    except QualificationJudgmentError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except (ValueError, RuntimeError, OpenAIError) as error:
        raise ApiError(502, "DOCUMENT_QA_FAILED", "문서 근거 응답을 안전하게 생성하지 못했습니다.") from error


@router.post("/actions/confirm", response_model=QualificationAnswerRead | QualificationRevalidationRead)
def copilot_confirm(
    payload: ConfirmAction,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
):
    authorize_case_access(db, user, payload.action.expected.case_id)
    try:
        return confirm_action(db, payload)
    except QualificationJudgmentError as error:
        db.rollback()
        raise ApiError(error.status_code, error.code, error.message) from error
