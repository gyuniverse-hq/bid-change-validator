"""공고 요약 · 판정 브리핑 · 챗봇의 HTTP 경계.

**이 라우터는 `main.py` 에 등록되어 있지 않습니다.** 등록에는 그 파일에 두 줄이
필요한데 Backend 소유라 손대지 않았습니다. 붙이실 때는 다른 라우터와 같은 방식으로:

    from .qualification_briefing_router import router as qualification_briefing_router
    ...
    app.include_router(qualification_briefing_router)

등록 전에도 동작을 확인하실 수 있게 단독 앱을 따로 두었습니다:

    uvicorn apps.api.app.llm_standalone:app --port 8100    # http://localhost:8100/docs

엔드포인트는 기존 경로 규칙(`/api/v1/...`)을 따르고 새 테이블·마이그레이션이
없습니다. 이미 저장된 분석·판정 결과를 읽어 조립할 뿐입니다.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .ai.briefing import ChatAnswer, NoticeBriefing
from .ai.notice_digest import NoticeDigest
from .ai.summary import NoticeSummary
from .database import get_db
from .errors import ApiError
from .qualification_briefing import (
    QualificationBriefingError,
    answer_for_judgment_run,
    build_briefing_for_judgment_run,
    build_notice_digest_for_version,
    narrate_briefing_for_judgment_run,
)


router = APIRouter(tags=["qualification briefing"])

_NOT_FOUND_CODES = {
    "NOTICE_VERSION_NOT_FOUND",
    "JUDGMENT_RUN_NOT_FOUND",
    "ANALYSIS_RUN_NOT_FOUND",
}


def _briefing_error(error: QualificationBriefingError) -> ApiError:
    status_code = 404 if error.code in _NOT_FOUND_CODES else 422
    return ApiError(status_code, error.code, error.message)


class ChatTurn(BaseModel):
    question: str
    answer: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    # 앞선 대화를 넣어야 "그럼 그건 왜?" 같은 이어지는 질문에 답할 수 있다.
    history: list[ChatTurn] = Field(default_factory=list)


@router.post(
    "/api/v1/notices/{notice_id}/versions/{version_number}/notice-digest",
    response_model=NoticeDigest,
    summary="공고 전체 요약 + 주제별 세부 요약",
)
def create_notice_digest(
    notice_id: UUID,
    version_number: int,
    db: Session = Depends(get_db),
) -> NoticeDigest:
    """공고문을 읽어 개요 한 단락과 주제 7종(개요·참가자격·과업·제출서류·평가·계약·일정)
    요약을 만든다. 각 주제는 근거 청크 id 를 달고 나간다.

    저장하지 않는다 — 결과를 남기려면 테이블이 필요하고 그건 DB 담당 영역이다.
    """
    try:
        return build_notice_digest_for_version(
            db, notice_id=notice_id, version_number=version_number
        )
    except QualificationBriefingError as error:
        raise _briefing_error(error) from error


@router.get(
    "/api/v1/qualification-judgment-runs/{run_id}/briefing",
    response_model=NoticeBriefing,
    summary="판정 결과 + 근거 조항 + 공고 요약 + 확인 필요 계약조항",
)
def get_judgment_briefing(
    run_id: UUID,
    include_digest: bool = True,
    include_clause_review: bool = True,
    db: Session = Depends(get_db),
) -> NoticeBriefing:
    """화면이 한 번에 그릴 수 있도록 조립된 브리핑.

    요건별 적/부와 사유, 그 판정이 딛고 선 공고 원문 인용, 판정 대상이 아니어서
    기록만 한 사항, 예규와 어긋나는 계약조항이 함께 들어간다.

    `include_digest=false` 로 요약 생성을 건너뛰면 LLM 호출 없이 즉시 응답한다.
    """
    try:
        return build_briefing_for_judgment_run(
            db,
            run_id,
            include_digest=include_digest,
            include_clause_review=include_clause_review,
        )
    except QualificationBriefingError as error:
        raise _briefing_error(error) from error


@router.post(
    "/api/v1/qualification-judgment-runs/{run_id}/briefing-narrative",
    response_model=NoticeSummary,
    summary="판정 결과를 구두 브리핑하듯 서술",
)
def create_briefing_narrative(
    run_id: UUID,
    db: Session = Depends(get_db),
) -> NoticeSummary:
    """확정된 판정을 문장으로 풀어쓴다. 판정을 바꾸거나 새로 만들지 않는다."""
    try:
        return narrate_briefing_for_judgment_run(db, run_id)
    except QualificationBriefingError as error:
        raise _briefing_error(error) from error


@router.post(
    "/api/v1/qualification-judgment-runs/{run_id}/chat",
    response_model=ChatAnswer,
    summary="판정 결과를 근거로 담당자 질문에 답변",
)
def chat_about_judgment(
    run_id: UUID,
    payload: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatAnswer:
    """도우미는 확정된 판정과 공고 원문 인용만 보고 답한다.

    새로 판정하지 않으며, 브리핑에 없는 이번 건의 사실은 모른다고 답한다.
    용어 설명처럼 일반적인 질문에는 자유롭게 답한다.
    """
    try:
        return answer_for_judgment_run(
            db,
            run_id,
            question=payload.question,
            history=[(turn.question, turn.answer) for turn in payload.history],
        )
    except QualificationBriefingError as error:
        raise _briefing_error(error) from error
