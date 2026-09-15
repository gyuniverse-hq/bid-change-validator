"""그래프 전용 API. 공고 분석·회사 판정·변경 비교를 분리하고 Copilot은 연결하지 않는다."""
from datetime import date
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from ...auth import authorize_case_access, get_optional_current_user
from ...auth_models import AppUser
from ...config import get_settings
from ...database import get_db
from ...errors import ApiError
from ...ai.providers.openai import OpenAIStructuredExtractor
from ..graph import service
from ..graph.document import GraphError
from ..analysis import QualificationAnalysisError
from ..judgment import QualificationJudgmentError
from .analysis import review_client_factory

router = APIRouter(prefix='/api/v1', tags=['qualification graph'])


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version_role: Literal['baseline','current']


class JudgeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    graph_run_id: UUID
    reference_date: date


def call(fn, db, **kwargs):
    try:
        return fn(db, **kwargs)
    except (GraphError, QualificationAnalysisError, QualificationJudgmentError) as error:
        db.rollback()
        code = str(error) if isinstance(error, GraphError) else error.code
        raise ApiError(404 if code.endswith('NOT_FOUND') else 409, code,
            '그래프의 대상·입력·분석 기준을 확인해 주세요. 기존 저장 결과는 덮어쓰지 않았습니다.') from error
    except SQLAlchemyError as error:
        db.rollback()
        raise ApiError(503, 'GRAPH_STORAGE_UNAVAILABLE', '그래프 저장소를 확인할 수 없습니다. 마이그레이션과 연결을 확인해 주세요.') from error


@router.get('/qualification-graph-options')
def options():
    return {'contract_version':'qualification-graph-options-v1', 'enabled': get_settings().qualification_graph_enabled,
            'legacy_default_unchanged': True, 'copilot_connected': False, 'requires_migration': '023_qualification_graphs'}


@router.get('/preflight-cases/{case_id}/qualification-graphs')
def list_runs(case_id: UUID, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)):
    authorize_case_access(db, user, case_id)
    return call(service.list_graphs, db, case_id=case_id)


@router.post('/preflight-cases/{case_id}/qualification-graphs', status_code=201)
def analyze(case_id: UUID, payload: AnalyzeRequest, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)):
    authorize_case_access(db, user, case_id)
    if not get_settings().qualification_graph_enabled:
        raise ApiError(409, 'GRAPH_STRATEGY_DISABLED', '그래프 분석이 이 서버에서 활성화되지 않았습니다.')
    extractor = OpenAIStructuredExtractor(client_factory=review_client_factory)
    if not extractor.available:
        raise ApiError(503, 'AI_PROVIDER_NOT_CONFIGURED', '모델 실행 환경이 구성되지 않았습니다.')
    return call(service.run_graph_analysis, db, case_id=case_id, version_role=payload.version_role, extractor=extractor)


@router.get('/preflight-cases/{case_id}/qualification-graphs/compare')
def compare(case_id: UUID, baseline_run_id: UUID, current_run_id: UUID,
            db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)):
    authorize_case_access(db, user, case_id)
    return call(service.compare_saved_graphs, db, case_id=case_id, baseline_run_id=baseline_run_id, current_run_id=current_run_id)


@router.get('/preflight-cases/{case_id}/qualification-graphs/{run_id}')
def get_run(case_id: UUID, run_id: UUID, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)):
    authorize_case_access(db, user, case_id)
    return call(service.read_graph, db, case_id=case_id, run_id=run_id)


@router.post('/preflight-cases/{case_id}/qualification-graph-judgments', status_code=201)
def judge(case_id: UUID, payload: JudgeRequest, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)):
    authorize_case_access(db, user, case_id)
    return call(service.judge_saved_graph, db, case_id=case_id, graph_run_id=payload.graph_run_id, reference_date=payload.reference_date)


@router.get('/preflight-cases/{case_id}/qualification-graph-judgments/{judgment_id}')
def get_judgment(case_id: UUID, judgment_id: UUID, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)):
    authorize_case_access(db, user, case_id)
    return call(service.read_graph_judgment, db, case_id=case_id, judgment_id=judgment_id)
