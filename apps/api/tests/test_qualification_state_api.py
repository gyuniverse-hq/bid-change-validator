"""실제 조회 서비스/라우터를 SQLite 최소 스키마와 연결해 검증한다.

운영 PostgreSQL ORM/마이그레이션/인증 및 프로필 생성은 대역이다.
상태 선택, 서비스 SQL, FastAPI 요청/응답은 실제 코드다. 모델 호출 없음.
"""
import importlib
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, String, Uuid, create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, relationship
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

ROOT = Path(__file__).resolve().parents[1] / 'app'
PKG = '_qualification_state_api_tests'


def module(name, **items):
    out = types.ModuleType(PKG + '.' + name)
    out.__dict__.update(items)
    sys.modules[out.__name__] = out
    return out


for name, path in [('', ROOT), ('.qualification', ROOT/'qualification'),
                   ('.qualification.routers', ROOT/'qualification/routers'),
                   ('.qualification.rules', ROOT/'qualification/rules')]:
    out = types.ModuleType(PKG + name)
    out.__path__ = [str(path)]
    sys.modules[out.__name__] = out


class UTCDateTime(TypeDecorator):
    """SQLite의 timezone 소실만 보완하는 테스트 타입."""
    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


Base = declarative_base()


class Case(Base):
    __tablename__ = 'cases'
    id = Column(Uuid, primary_key=True)
    notice_id = Column(Uuid)
    current_version_id = Column(Uuid)
    company_id = Column(Uuid, nullable=True)


class Version(Base):
    __tablename__ = 'versions'
    id = Column(Uuid, primary_key=True)
    notice_id = Column(Uuid)


class Company(Base):
    __tablename__ = 'companies'
    id = Column(Uuid, primary_key=True)
    payload = Column(JSON)


class Completeness(Base):
    __tablename__ = 'completeness'
    company_id = Column(Uuid, primary_key=True)


class Analysis(Base):
    __tablename__ = 'analyses'
    id = Column(Uuid, primary_key=True)
    notice_version_id = Column(Uuid, ForeignKey('versions.id'))
    status = Column(String)
    contract_version = Column(String, default='ai-analysis-v0.2')
    analysis_kind = Column(String, default='QUALIFICATION_REQUIREMENTS')
    created_at = Column(UTCDateTime)
    diagnostics = Column(JSON, default=list)
    dropped_requirements = Column(JSON, default=list)
    notice_version = relationship(Version)
    requirements = relationship('Requirement')
    evidence = relationship('Evidence')


class Requirement(Base):
    __tablename__ = 'requirements'
    id = Column(Uuid, primary_key=True, default=uuid4)
    analysis_run_id = Column(Uuid, ForeignKey('analyses.id'))
    requirement_key = Column(String)
    evidence_keys = Column(JSON)


class Evidence(Base):
    __tablename__ = 'evidence'
    id = Column(Uuid, primary_key=True, default=uuid4)
    analysis_run_id = Column(Uuid, ForeignKey('analyses.id'))
    evidence_key = Column(String)
    notice_version_id = Column(String)


class JudgmentRun(Base):
    __tablename__ = 'judgment_runs'
    id = Column(Uuid, primary_key=True)
    preflight_case_id = Column(Uuid)
    company_id = Column(Uuid)
    notice_version_id = Column(Uuid)
    analysis_run_id = Column(Uuid)
    created_at = Column(UTCDateTime)
    rule_version = Column(String)
    analysis_status = Column(String)
    overall_status = Column(String)
    reference_date = Column(Date)
    profile_snapshot = Column(JSON)
    judgments = relationship('Judgment')


class Judgment(Base):
    __tablename__ = 'judgments'
    id = Column(Uuid, primary_key=True, default=uuid4)
    judgment_run_id = Column(Uuid, ForeignKey('judgment_runs.id'))
    requirement_key = Column(String)
    requirement_evidence_keys = Column(JSON)
    status = Column(String)
    rule_version = Column(String)
    basis_type = Column(String)
    value_source = Column(String)
    unknown_reason = Column(String, nullable=True)


class JudgmentError(ValueError):
    def __init__(self, code, message, status_code=409):
        self.code, self.message, self.status_code = code, message, status_code


class ApiError(Exception):
    def __init__(self, status_code, code, message, details=None):
        self.status_code, self.code, self.message, self.details = status_code, code, message, details


module('models', PreflightCase=Case)
module('analysis_models', QualificationAnalysisRun=Analysis)
module('judgment_models', QualificationJudgmentRun=JudgmentRun, CompanyQualificationProfileCompleteness=Completeness)
module('qualification.rules.judgment', RULE_VERSION='rules-3')
module('qualification.judgment', QualificationJudgmentError=JudgmentError,
       _load_company=lambda db, key: db.get(Company, key), _record_to_completeness=lambda row: None,
       build_company_profile_snapshot=lambda company, completeness: NS(model_dump=lambda **kwargs: company.payload))
module('errors', ApiError=ApiError)


class AppUser:
    pass


module('auth_models', AppUser=AppUser)


def get_db():
    raise AssertionError('dependency must be overridden')


def get_user():
    return AppUser()


def authorize(db, user, case_id):
    pass


module('database', get_db=get_db)
module('auth', authorize_case_access=authorize, get_optional_current_user=get_user)
service = importlib.import_module(PKG + '.qualification.state_service')
router_module = importlib.import_module(PKG + '.qualification.routers.state')
DAY = date(2026, 9, 15)
NOW = datetime(2026, 9, 15, 9, tzinfo=timezone.utc)


@pytest.fixture
def world():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    cid, vid, nid, coid, aid, jid = (uuid4() for _ in range(6))
    profile = {'company_id': str(coid), 'industries': [{'code': '1450'}], 'completeness': {'industries': True}}
    case = Case(id=cid, current_version_id=vid, notice_id=nid, company_id=coid)
    a = Analysis(id=aid, notice_version_id=vid, status='SUCCEEDED', created_at=NOW, diagnostics=[], dropped_requirements=[])
    a.requirements = [Requirement(requirement_key='R1', evidence_keys=['E1'])]
    a.evidence = [Evidence(evidence_key='E1', notice_version_id=str(vid))]
    j = JudgmentRun(id=jid, preflight_case_id=cid, notice_version_id=vid, company_id=coid, analysis_run_id=aid,
        created_at=NOW, rule_version='rules-3', analysis_status='SUCCEEDED', reference_date=DAY,
        profile_snapshot=profile, overall_status='eligible')
    j.judgments = [Judgment(requirement_key='R1', requirement_evidence_keys=['E1'], status='SATISFIED',
        rule_version='rules-3', basis_type='PROFILE', value_source='stored_profile')]
    db.add_all([case, Version(id=vid, notice_id=nid), Company(id=coid, payload=profile), a, j])
    db.commit()
    queries = []
    event.listen(engine, 'before_cursor_execute', lambda conn, cursor, statement, parameters, context, many: queries.append(statement))
    app = FastAPI()
    parent = APIRouter(prefix='/api/v1')
    parent.include_router(router_module.router)
    app.include_router(parent)
    app.dependency_overrides[get_db] = lambda: db

    @app.exception_handler(ApiError)
    async def handle(request, error):
        return JSONResponse(status_code=error.status_code, content={'error': {'code': error.code, 'message': error.message}})

    with TestClient(app) as client:
        yield NS(db=db, engine=engine, case=case, a=a, j=j, company=coid, profile=profile,
                 client=client, path=f'/api/v1/preflight-cases/{cid}/qualification-state', queries=queries)
    db.close()
    engine.dispose()


def test_service_reads_actual_sqlite_rows_without_writes(world):
    result = service.read_qualification_state(world.db, case_id=world.case.id, reference_date=DAY)
    assert result.selected_judgment_run_id == str(world.j.id)
    assert result.freshness_state == 'CURRENT'
    assert all(not query.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for query in world.queries)


def test_http_endpoint_is_registered_once_with_the_right_prefix(world):
    response = world.client.get(world.path, params={'reference_date': DAY.isoformat()})
    assert response.status_code == 200
    result = response.json()
    assert result['contract_version'] == 'qualification-state-v1'
    assert result['selected_judgment_run_id'] == str(world.j.id)
    assert 'state_sha256' in result
    assert 'industries' not in response.text and 'E1' not in response.text
    assert world.client.get('/api/v1' + world.path).status_code == 404


def test_missing_reference_date_is_not_silently_today(world):
    result = world.client.get(world.path).json()
    assert result['freshness_state'] == 'CHECKS_INCOMPLETE'
    assert result['requested_reference_date'] is None
    assert result['stored_reference_date'] == DAY.isoformat()


def test_profile_change_exposes_rejudgment_not_unreviewed(world):
    company = world.db.get(Company, world.company)
    company.payload = {**company.payload, 'industries': []}
    world.db.commit()
    result = world.client.get(world.path).json()
    assert result['display_state'] == 'REJUDGMENT_REQUIRED'
    assert 'PROFILE_CHANGED' in result['reasons']
    assert result['selected_judgment_run_id'] is None
    assert result['stored_overall_status'] == 'eligible'


def test_latest_failed_analysis_hides_old_current_verdict(world):
    new = Analysis(id=uuid4(), notice_version_id=world.case.current_version_id, status='FAILED', created_at=NOW+timedelta(hours=1))
    world.db.add(new)
    world.db.commit()
    result = world.client.get(world.path).json()
    assert result['analysis_run_id'] == str(new.id)
    assert result['display_state'] == 'ANALYSIS_FAILED'
    assert result['selected_judgment_run_id'] is None


def test_new_analysis_requires_its_own_judgment(world):
    new = Analysis(id=uuid4(), notice_version_id=world.case.current_version_id, status='SUCCEEDED', created_at=NOW+timedelta(hours=1))
    new.requirements = [Requirement(requirement_key='R1', evidence_keys=['E2'])]
    new.evidence = [Evidence(evidence_key='E2', notice_version_id=str(world.case.current_version_id))]
    world.db.add(new)
    world.db.commit()
    result = world.client.get(world.path).json()
    assert result['display_state'] == 'REJUDGMENT_REQUIRED'
    assert 'ANALYSIS_CHANGED' in result['reasons']


def test_old_rule_never_becomes_current(world):
    world.j.rule_version = 'rules-2'
    world.db.commit()
    result = world.client.get(world.path).json()
    assert 'RULE_VERSION_CHANGED' in result['reasons']
    assert result['selected_judgment_run_id'] is None


def test_no_analysis_is_distinct_from_no_judgment(world):
    world.db.delete(world.j)
    world.db.commit()
    assert world.client.get(world.path).json()['display_state'] == 'JUDGMENT_REQUIRED'
    world.db.delete(world.a)
    world.db.commit()
    assert world.client.get(world.path).json()['display_state'] == 'UNREVIEWED'


def test_pending_changes_are_not_flushed_by_auth_or_state_reads(world, monkeypatch):
    pending = Company(id=uuid4(), payload={'private': 'not yet saved'})
    world.db.add(pending)
    monkeypatch.setattr(router_module, 'authorize_case_access', lambda db, user, key: db.scalar(select(Case).where(Case.id == key)))
    world.queries.clear()
    assert world.client.get(world.path).status_code == 200
    assert pending in world.db.new
    assert all(not query.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for query in world.queries)


def test_unauthorized_access_is_blocked_before_state_read(world, monkeypatch):
    def deny(*args):
        raise ApiError(403, 'FORBIDDEN', '권한 없음')
    monkeypatch.setattr(router_module, 'authorize_case_access', deny)
    world.queries.clear()
    response = world.client.get(world.path)
    assert response.status_code == 403
    assert not world.queries
    assert str(world.a.id) not in response.text


def test_database_error_is_503_not_successful_empty_data(world, monkeypatch):
    def failure(*args, **kwargs):
        raise OperationalError('PRIVATE_SQL', 'SECRET_DB_URL', Exception('password'))
    monkeypatch.setattr(world.db, 'scalar', failure)
    response = world.client.get(world.path)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'QUALIFICATION_STATE_UNAVAILABLE'
    assert 'PRIVATE_SQL' not in response.text and 'SECRET_DB_URL' not in response.text


def test_bad_profile_payload_has_explicit_409(world):
    world.j.profile_snapshot = ['broken']
    world.db.commit()
    response = world.client.get(world.path)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'QUALIFICATION_STATE_INVALID'


@pytest.mark.parametrize('mutation', ['missing_evidence', 'foreign_evidence', 'duplicate_judgment', 'changed_status', 'snapshot_company'])
def test_broken_links_return_data_invalid_not_current(world, mutation):
    if mutation == 'missing_evidence':
        world.a.requirements[0].evidence_keys = ['MISSING']
    if mutation == 'foreign_evidence':
        world.a.evidence[0].notice_version_id = str(uuid4())
    if mutation == 'duplicate_judgment':
        world.j.judgments.append(Judgment(requirement_key='R1', requirement_evidence_keys=['E1'], status='SATISFIED', rule_version='rules-3', basis_type='PROFILE', value_source='stored_profile'))
    if mutation == 'changed_status':
        world.j.analysis_status = 'PARTIAL'
    if mutation == 'snapshot_company':
        world.j.profile_snapshot = {**world.profile, 'company_id': str(uuid4())}
    world.db.commit()
    result = world.client.get(world.path).json()
    assert result['display_state'] == 'DATA_INVALID'
    assert result['selected_judgment_run_id'] is None


def test_empty_canonical_never_returns_eligible(world):
    world.a.requirements = []
    world.db.commit()
    result = world.client.get(world.path).json()
    assert result['display_state'] == 'ANALYSIS_INCOMPLETE'
    assert result['stored_overall_status'] is None


def test_company_required_has_explicit_state(world):
    world.case.company_id = None
    world.db.commit()
    assert world.client.get(world.path).json()['display_state'] == 'PROFILE_REQUIRED'


def test_unknown_case_and_invalid_date_have_distinct_http_errors(world):
    assert world.client.get(world.path.replace(str(world.case.id), str(uuid4()))).status_code == 404
    assert world.client.get(world.path, params={'reference_date': 'not-a-date'}).status_code == 422


def test_partial_keeps_stored_verdict_and_warns_about_analysis(world):
    world.a.status = world.j.analysis_status = 'PARTIAL'
    world.j.overall_status = 'ineligible'
    world.db.commit()
    result = world.client.get(world.path).json()
    assert result['execution_state'] == 'PARTIAL'
    assert result['stored_overall_status'] == 'ineligible'
    assert result['display_state'] == 'ANALYSIS_INCOMPLETE'


def test_user_answer_basis_is_not_claimed_fresh(world):
    world.j.judgments[0].basis_type = 'USER_ANSWER'
    world.j.judgments[0].value_source = 'askback'
    world.db.commit()
    result = world.client.get(world.path, params={'reference_date': DAY.isoformat()}).json()
    assert result['answer_basis_check'] == 'UNVERIFIED'
    assert result['freshness_state'] == 'CHECKS_INCOMPLETE'


def test_new_analysis_contract_is_not_silently_treated_as_legacy(world):
    world.a.contract_version = 'unknown-graph-contract'
    world.db.commit()
    result = world.client.get(world.path).json()
    assert result['display_state'] == 'DATA_INVALID'


def test_latest_basis_change_during_read_requires_refresh(world, monkeypatch):
    original = world.db.execute
    def execute(statement, *args, **kwargs):
        if str(statement).startswith('SELECT analyses.id, analyses.status'):
            return NS(first=lambda: (uuid4(), 'SUCCEEDED'))
        return original(statement, *args, **kwargs)
    monkeypatch.setattr(world.db, 'execute', execute)
    response = world.client.get(world.path)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'QUALIFICATION_STATE_CHANGED'


def test_semantic_entrypoint_adds_state_without_rewriting_analysis(monkeypatch):
    semantic = importlib.import_module(PKG + '.qualification.semantic_state')
    decision = NS(candidate_id='C', status='REQUIREMENT', pending_codes=())
    judgment = NS(candidate_id='C', status='UNKNOWN', pending_codes=(), role='mandatory',
        context_sha256='ctx', company_id='CO', rule_version='rule')
    execution = NS(decisions=(decision,), invalid_candidate_ids=(),
        coverage=NS(candidate_count=1, processed_count=1, coverage_status='COMPLETE'),
        plan=NS(target_candidate_ids=('C',), blocked=(), inventory=NS(source_gaps=())))
    analysis = NS(notice_id='N', notice_version_id='V', execution=execution, judgments=(judgment,))
    seen = []
    def analyze(*args, **kwargs):
        seen.append((args, kwargs))
        return analysis
    module('ai.qualification.extraction.review_semantic_judgment', analyze_qualification_semantics=analyze)
    result = semantic.analyze_semantics_with_state('input', reference_date=DAY)
    assert seen == [(('input',), {'reference_date': DAY})]
    assert result.analysis is analysis
    assert result.state['clause_judgment_counts']['UNKNOWN'] == 1
    assert result.state['notice_overall_status'] is None
