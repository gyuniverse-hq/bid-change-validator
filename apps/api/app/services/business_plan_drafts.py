"""사전검토 사건의 판정 결과로 사업계획서 초안을 만든다.

프론트가 보내는 것은 사건 ID 와 담당자 입력뿐이다
-----------------------------------------------
초안의 근거인 검토 브리핑은 **서버가 판정 실행에서 직접 만든다.** 클라이언트가
브리핑 텍스트를 실어 보내는 형태로 짜면 근거를 위조할 수 있고, 그러면 "참가 불가"인
공고에 "전부 충족"이라 적힌 초안이 나온다. 측정에서 확인한 것은 사용자 입력을 통한
인젝션을 모델이 막는다는 것이지, 위조된 근거를 걸러낸다는 뜻이 아니다 — 그건 모델이
알 수 없다.

무엇을 읽나
-----------
    판정 실행(QualificationJudgmentRun) -> judgments[]   상태·reason_code
    그 실행의 분석(analysis_run) -> requirements[]      요건 원문·유형·값
    공고 버전 -> 제목

이 셋을 `briefing_text.render_briefing` 으로 엮어 생성기에 넘긴다. 조판은 코드이고
모델은 생성기 안에서 한 번만 불린다.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..ai.narration import Narrator
from ..ai.narration.briefing_text import render_briefing, verify_round_trip
from ..ai.narration.business_plan import (
    BusinessPlanDraft,
    BusinessPlanInputs,
    generate_business_plan_draft,
)
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import QualificationJudgmentRun
from ..models import BidNoticeVersion, PreflightCase


class BusinessPlanDraftError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _load_judgment_run(
    db: Session, *, case_id: UUID, judgment_run_id: UUID | None
) -> QualificationJudgmentRun:
    """지정한 실행, 없으면 그 사건의 최신 실행."""
    if db.get(PreflightCase, case_id) is None:
        raise BusinessPlanDraftError(
            "PREFLIGHT_CASE_NOT_FOUND", "사전검토 사건을 찾을 수 없습니다.", status_code=404
        )
    query = (
        select(QualificationJudgmentRun)
        .where(QualificationJudgmentRun.preflight_case_id == case_id)
        .options(
            selectinload(QualificationJudgmentRun.judgments),
            selectinload(QualificationJudgmentRun.analysis_run).selectinload(
                QualificationAnalysisRun.requirements
            ),
        )
    )
    if judgment_run_id is not None:
        query = query.where(QualificationJudgmentRun.id == judgment_run_id)
    else:
        query = query.order_by(QualificationJudgmentRun.created_at.desc()).limit(1)
    run = db.scalar(query)
    if run is None:
        # 두 상황은 담당자가 할 일이 다르다. 판정이 아예 없으면 판정을 돌려야 하고,
        # 지정한 ID 가 틀렸으면 ID 를 고쳐야 한다. 같은 오류로 뭉치면 "판정 먼저"
        # 안내를 보고 이미 판정한 사건에서 헤맨다 — Swagger 예시 UUID 를 그대로
        # 보낸 첫 시연에서 실제로 그랬다.
        if judgment_run_id is not None:
            raise BusinessPlanDraftError(
                "JUDGMENT_RUN_NOT_FOUND",
                "지정한 판정 실행이 이 사건에 없습니다. judgment_run_id 를 비우면 최신 판정을 씁니다.",
                status_code=404,
            )
        raise BusinessPlanDraftError(
            "JUDGMENT_RUN_REQUIRED",
            "참가자격 판정이 아직 없습니다. 판정을 먼저 실행해 주세요.",
        )
    return run


def build_briefing_for_run(db: Session, run: QualificationJudgmentRun) -> str:
    """판정 실행 하나를 초안 생성기가 읽을 문자열로 엮는다. 행을 버리지 않는다."""
    requirements = {
        record.requirement_key: record for record in run.analysis_run.requirements
    }
    raw_by_key = {key: record.raw for key, record in requirements.items()}
    type_by_key = {key: record.type for key, record in requirements.items()}

    judgments: list[dict[str, Any]] = [
        {
            "requirement_key": record.requirement_key,
            "status": record.status,
            "reason_code": record.reason_code,
            "profile_refs": list(record.profile_refs or []),
        }
        for record in sorted(run.judgments, key=lambda item: item.requirement_key)
    ]

    # 제목은 공고(bid_notices.title)에 있고 버전에는 없다.
    version = db.get(BidNoticeVersion, run.notice_version_id)
    title = version.notice.title if version is not None and version.notice else None

    briefing = render_briefing(
        judgments, run.overall_status, raw_by_key, type_by_key, notice_title=title
    )
    # 조판이 행을 빠뜨리면 초안이 그 요건을 숨긴 것처럼 보인다. 생성기 파서와
    # 같은 규칙으로 되읽어 전부 살아 있는지 확인한다.
    verify_round_trip(briefing, judgments, type_by_key)
    return briefing


def draft_business_plan_for_case(
    db: Session,
    *,
    case_id: UUID,
    inputs: BusinessPlanInputs,
    judgment_run_id: UUID | None = None,
    narrate: Narrator | None,
) -> BusinessPlanDraft:
    run = _load_judgment_run(db, case_id=case_id, judgment_run_id=judgment_run_id)
    briefing = build_briefing_for_run(db, run)
    flagged = sum(1 for item in run.judgments if item.status in ("UNSATISFIED", "UNKNOWN"))
    return generate_business_plan_draft(
        briefing,
        inputs,
        notice_id=str(run.notice_version_id),
        judgment_count=len(run.judgments),
        flagged_clause_count=flagged,
        narrate=narrate,
    )
