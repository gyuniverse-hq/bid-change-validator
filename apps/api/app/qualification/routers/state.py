"""조회 실패와 미검토를 분리하는 읽기 전용 상태 API. 기존 판정 응답은 바꾸지 않는다."""
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...auth import authorize_case_access, get_optional_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...errors import ApiError
from ..judgment import QualificationJudgmentError
from ..state_contract import StateInputError
from ..state_service import read_qualification_state

router = APIRouter(tags=["qualification state"])


@router.get("/preflight-cases/{case_id}/qualification-state")
def get_qualification_state(
    case_id: UUID,
    reference_date: date | None = None,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> dict[str, Any]:
    # 상태의 존재 여부도 타 회사에 노출하지 않는다. 권한 오류를 조회실패로 바꾸지 않는다.
    try:
        with db.no_autoflush:
            authorize_case_access(db, user, case_id)
            return read_qualification_state(db, case_id=case_id, reference_date=reference_date).to_dict()
    except QualificationJudgmentError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except StateInputError as error:
        if error.args == ("STATE_BASIS_CHANGED_DURING_READ",):
            raise ApiError(409, "QUALIFICATION_STATE_CHANGED", "조회 중 분석 기준이 바뀌었습니다. 다시 조회해 주세요.") from error
        raise ApiError(409, "QUALIFICATION_STATE_INVALID", "저장된 분석·판정의 기준 또는 연결을 확인해야 합니다.") from error
    except SQLAlchemyError as error:
        # SQL/DB 주소/예외 원문을 노출하지 않고, 빈 목록을 반환하지도 않는다.
        raise ApiError(503, "QUALIFICATION_STATE_UNAVAILABLE", "판정 상태를 불러오지 못했습니다. 다시 조회해 주세요.") from error


# 부모 judgment router의 /api/v1 prefix를 그대로 사용한다.
from .catalog import router as catalog_router

router.include_router(catalog_router)
