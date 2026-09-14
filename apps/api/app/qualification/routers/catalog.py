"""같은 검색 범위의 공고·저장 판정·유형/상태 집계를 읽는 API."""
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...auth import authorize_company_access, get_optional_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...errors import ApiError
from ..judgment import QualificationJudgmentError
from ..notice_catalog import read_notice_catalog
from ..state_contract import StateInputError

router = APIRouter(tags=["qualification catalog"])


@router.get("/qualification-notice-catalog")
def get_notice_catalog(
    company_id: UUID | None = None,
    q: Annotated[str, Query(max_length=200)] = "",
    business_type: Literal["SERVICE", "GOODS", "CONSTRUCTION", "FOREIGN"] | None = None,
    status: Literal["eligible", "insufficient_data", "ineligible", "unreviewed"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    reference_date: date | None = None,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> dict[str, Any]:
    try:
        with db.no_autoflush:
            if company_id is not None:
                authorize_company_access(user, company_id)
            return read_notice_catalog(db, company_id=company_id, q=q, business_type=business_type,
                                       status=status, limit=limit, offset=offset, reference_date=reference_date)
    except QualificationJudgmentError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except StateInputError as error:
        if error.args == ("CATALOG_SCOPE_TOO_LARGE",):
            raise ApiError(422, "CATALOG_SCOPE_TOO_LARGE", "정확한 상태 집계를 위해 공고명·공고번호로 검색 범위를 좁혀 주세요.") from error
        if error.args == ("STATE_BASIS_CHANGED_DURING_READ",):
            raise ApiError(409, "QUALIFICATION_STATE_CHANGED", "조회 중 공고나 분석 기준이 바뀌었습니다. 다시 조회해 주세요.") from error
        raise ApiError(409, "QUALIFICATION_CATALOG_INVALID", "공고와 판정의 연결 상태를 확인해야 합니다.") from error
    except SQLAlchemyError as error:
        raise ApiError(503, "QUALIFICATION_CATALOG_UNAVAILABLE", "공고와 판정 상태를 불러오지 못했습니다. 다시 시도해 주세요.") from error
