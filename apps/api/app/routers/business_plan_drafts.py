"""사업계획서 초안 생성 엔드포인트.

    POST /api/v1/preflight-cases/{case_id}/business-plan-draft

프론트가 보내는 것은 담당자 입력 일곱 칸(전부 선택)과 선택적 judgment_run_id 뿐이다.
검토 브리핑은 서버가 판정 실행에서 만든다 — 클라이언트가 만들어 보내면 근거를 위조할
수 있다.

모델 호출이 실패해도 200 + status 로 돌려준다. 초안 생성 실패는 서버 장애가 아니라
결과의 한 종류이고, 화면이 사유(입력 없음 / 키 없음 / 판정 없음 / 모델 실패)마다 다르게
안내해야 한다. 그 사유들을 "생성 실패" 하나로 뭉치면 사용자가 고칠 수 있는 것과 없는
것이 섞인다.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..ai.narration.business_plan import BusinessPlanDraft, BusinessPlanInputs
from ..ai.providers.openai import OpenAINarrator
from ..database import get_db
from ..errors import ApiError
from ..services.business_plan_drafts import (
    BusinessPlanDraftError,
    draft_business_plan_for_case,
)


router = APIRouter(tags=["business plan drafts"])


class BusinessPlanDraftRequest(BaseModel):
    judgment_run_id: UUID | None = None
    inputs: BusinessPlanInputs = Field(default_factory=BusinessPlanInputs)


@router.post(
    "/api/v1/preflight-cases/{case_id}/business-plan-draft",
    response_model=BusinessPlanDraft,
    summary="사전검토 사건의 판정 결과로 사업계획서 초안을 만든다",
)
def create_business_plan_draft(
    case_id: UUID,
    payload: BusinessPlanDraftRequest,
    db: Session = Depends(get_db),
) -> BusinessPlanDraft:
    narrator = OpenAINarrator()
    try:
        return draft_business_plan_for_case(
            db,
            case_id=case_id,
            inputs=payload.inputs,
            judgment_run_id=payload.judgment_run_id,
            # 키가 없으면 None 을 넘겨 생성기가 NARRATOR_UNAVAILABLE 로 답하게 한다.
            narrate=narrator if narrator.available else None,
        )
    except BusinessPlanDraftError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
