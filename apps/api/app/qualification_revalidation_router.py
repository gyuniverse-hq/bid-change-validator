"""HTTP route for changed-notice qualification revalidation."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .database import get_db
from .errors import ApiError
from .qualification_judgment import QualificationJudgmentError
from .qualification_revalidation import run_qualification_revalidation
from .revalidation_schemas import QualificationRevalidationCreate, QualificationRevalidationRead


router = APIRouter(prefix="/api/v1", tags=["qualification revalidation"])


def _as_api_error(error: QualificationJudgmentError) -> ApiError:
    return ApiError(error.status_code, error.code, error.message)


@router.post(
    "/preflight-cases/{case_id}/qualification-revalidation",
    response_model=QualificationRevalidationRead,
)
def trigger_qualification_revalidation(
    case_id: UUID,
    payload: QualificationRevalidationCreate,
    db: Session = Depends(get_db),
) -> QualificationRevalidationRead:
    try:
        return run_qualification_revalidation(db, case_id=case_id, payload=payload)
    except QualificationJudgmentError as error:
        raise _as_api_error(error) from error
