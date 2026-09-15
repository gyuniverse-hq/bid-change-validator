"""HTTP boundary for persisted qualification Requirement analysis runs."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...ai.providers.openai import OpenAIStructuredExtractor
from ...analysis_schemas import QualificationAnalysisRequest, QualificationAnalysisRunRead, QualificationAnalysisRunSummary
from ...config import get_settings
from ...database import get_db
from ...errors import ApiError
from ..analysis import (
    QualificationAnalysisError,
    analysis_run_response,
    list_qualification_analysis_runs,
    load_qualification_analysis_run,
    run_qualification_analysis,
)


router = APIRouter(tags=["qualification analysis"])


def _analysis_error(error: QualificationAnalysisError) -> ApiError:
    status_code = 404 if error.code in {"NOTICE_VERSION_NOT_FOUND", "ANALYSIS_RUN_NOT_FOUND"} else 422
    if error.code == "ANALYSIS_SOURCE_CHANGED":
        status_code = 409
    if error.code == "EXTRACTION_STRATEGY_DISABLED":
        status_code = 409
    return ApiError(status_code, error.code, error.message)


def review_client_factory(api_key: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, timeout=60.0, max_retries=0)


@router.get("/api/v1/qualification-analysis-options")
def qualification_analysis_options() -> dict:
    return {"contract_version": "qualification-analysis-options-v1", "default_strategy": "legacy",
            "strategies": [
                {"id": "legacy", "enabled": True},
                {"id": "review_v1", "enabled": get_settings().qualification_review_v1_enabled},
            ], "graph_product_enabled": False}


@router.post(
    "/api/v1/notices/{notice_id}/versions/{version_number}/qualification-analysis",
    response_model=QualificationAnalysisRunRead,
    status_code=status.HTTP_201_CREATED,
)
def trigger_qualification_analysis(
    notice_id: UUID,
    version_number: int,
    payload: QualificationAnalysisRequest | None = None,
    db: Session = Depends(get_db),
) -> QualificationAnalysisRunRead:
    request = payload or QualificationAnalysisRequest()
    if request.extraction_strategy == "review_v1" and not get_settings().qualification_review_v1_enabled:
        raise ApiError(409, "EXTRACTION_STRATEGY_DISABLED", "조항별 검토 경로가 이 서버에서 활성화되지 않았습니다.")
    extractor = (OpenAIStructuredExtractor(client_factory=review_client_factory)
                 if request.extraction_strategy == "review_v1" else OpenAIStructuredExtractor())
    if not extractor.available:
        raise ApiError(
            503,
            "AI_PROVIDER_NOT_CONFIGURED",
            "OPENAI_API_KEY가 설정되지 않아 자격요건 분석을 실행할 수 없습니다.",
        )
    try:
        run = run_qualification_analysis(
            db,
            notice_id=notice_id,
            version_number=version_number,
            structured_extract=extractor,
            extraction_strategy=request.extraction_strategy,
        )
    except QualificationAnalysisError as error:
        raise _analysis_error(error) from error
    except RuntimeError as error:
        raise ApiError(502, "AI_ANALYSIS_FAILED", "자격요건 분석을 완료하지 못했습니다. 제공자 상태와 실행 기록을 확인해 주세요.") from error
    return analysis_run_response(run)


@router.get(
    "/api/v1/notices/{notice_id}/versions/{version_number}/qualification-analyses",
    response_model=list[QualificationAnalysisRunSummary],
)
def list_version_qualification_analyses(
    notice_id: UUID,
    version_number: int,
    db: Session = Depends(get_db),
) -> list[QualificationAnalysisRunSummary]:
    try:
        return list_qualification_analysis_runs(
            db, notice_id=notice_id, version_number=version_number
        )
    except QualificationAnalysisError as error:
        raise _analysis_error(error) from error


@router.get(
    "/api/v1/qualification-analyses/{run_id}",
    response_model=QualificationAnalysisRunRead,
)
def get_qualification_analysis(
    run_id: UUID,
    db: Session = Depends(get_db),
) -> QualificationAnalysisRunRead:
    try:
        return analysis_run_response(load_qualification_analysis_run(db, run_id))
    except QualificationAnalysisError as error:
        raise _analysis_error(error) from error
