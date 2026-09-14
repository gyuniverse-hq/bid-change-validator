"""실제 카탈로그 SQL/상태 선택/HTTP 검증. 운영 ORM·인증·회사 로더만 분리한다.

SQLite 최소 스키마는 운영 PostgreSQL 회귀를 대체하지 않는다.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL, UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Uuid, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

ROOT = Path(__file__).resolve().parents[1] / 'app'
PKG = '_notice_catalog_step6'
for name, path in [(PKG, ROOT), (f'{PKG}.qualification', ROOT / 'qualification'),
                   (f'{PKG}.qualification.routers', ROOT / 'qualification/routers'),
                   (f'{PKG}.qualification.rules', ROOT / 'qualification/rules')]:
    m = types.ModuleType(name); m.__path__ = [str(path)]; sys.modules[name] = m


def uid(text): return uuid5(NAMESPACE_URL, text)
NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)
DAY = date(2026, 9, 15)
COMPANY = uid('company')
OTHER = uid('other')


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True
    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase): pass

class BidNotice(Base):
    __tablename__ = 'bid_notices'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    bid_notice_no: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    business_type: Mapped[str] = mapped_column(String)
    notice_kind: Mapped[str | None] = mapped_column(String)
    announcing_institution_name: Mapped[str | None] = mapped_column(String)
    demanding_institution_name: Mapped[str | None] = mapped_column(String)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)

class BidNoticeVersion(Base):
    __tablename__ = 'bid_notice_versions'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    notice_id: Mapped[UUID] = mapped_column(ForeignKey('bid_notices.id'))
    version_number: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean)

class PreflightCase(Base):
    __tablename__ = 'preflight_cases'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    notice_id: Mapped[UUID] = mapped_column(Uuid)
    current_version_id: Mapped[UUID] = mapped_column(Uuid)
    company_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

class QualificationAnalysisRun(Base):
    __tablename__ = 'qualification_analysis_runs'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    notice_version_id: Mapped[UUID] = mapped_column(ForeignKey('bid_notice_versions.id'))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String)
    contract_version: Mapped[str] = mapped_column(String, default='ai-analysis-v0.2')
    analysis_kind: Mapped[str] = mapped_column(String, default='QUALIFICATION_REQUIREMENTS')
    diagnostics: Mapped[list] = mapped_column(JSON, default=list)
    dropped_requirements: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[list['QualificationRequirementRecord']] = relationship()
    evidence: Mapped[list['QualificationEvidenceRecord']] = relationship()
    notice_version: Mapped[BidNoticeVersion] = relationship()

class QualificationRequirementRecord(Base):
    __tablename__ = 'qualification_requirements'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey('qualification_analysis_runs.id'))
    requirement_key: Mapped[str] = mapped_column(String)
    evidence_keys: Mapped[list] = mapped_column(JSON)
    raw: Mapped[str] = mapped_column(String, default='PRIVATE_SOURCE_NOT_FOR_CATALOG')

class QualificationEvidenceRecord(Base):
    __tablename__ = 'qualification_evidence'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey('qualification_analysis_runs.id'))
    evidence_key: Mapped[str] = mapped_column(String)
    notice_version_id: Mapped[str] = mapped_column(String)
    quote: Mapped[str] = mapped_column(String, default='PRIVATE_QUOTE_NOT_FOR_CATALOG')

class CompanyQualificationProfileCompleteness(Base):
    __tablename__ = 'company_qualification_profile_completeness'
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)

class QualificationJudgmentRun(Base):
    __tablename__ = 'qualification_judgment_runs'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    preflight_case_id: Mapped[UUID] = mapped_column(Uuid)
    company_id: Mapped[UUID] = mapped_column(Uuid)
    notice_version_id: Mapped[UUID] = mapped_column(Uuid)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey('qualification_analysis_runs.id'))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    rule_version: Mapped[str] = mapped_column(String, default='qualification-rules-v0.3')
    analysis_status: Mapped[str] = mapped_column(String)
    reference_date: Mapped[date] = mapped_column(Date)
    profile_snapshot: Mapped[dict] = mapped_column(JSON)
    overall_status: Mapped[str] = mapped_column(String)
    judgments: Mapped[list['QualificationJudgmentRecord']] = relationship()

class QualificationJudgmentRecord(Base):
    __tablename__ = 'qualification_judgments'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    judgment_run_id: Mapped[UUID] = mapped_column(ForeignKey('qualification_judgment_runs.id'))
    requirement_key: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    rule_version: Mapped[str | None] = mapped_column(String)
    unknown_reason: Mapped[str | None] = mapped_column(String)
    basis_type: Mapped[str] = mapped_column(String, default='PROFILE')
    value_source: Mapped[str] = mapped_column(String, default='stored_profile')
    requirement_evidence_keys: Mapped[list] = mapped_column(JSON)


def module(name, **values):
    m = types.ModuleType(f'{PKG}.{name}'); m.__dict__.update(values); sys.modules[m.__name__] = m; return m
module('models', BidNotice=BidNotice, BidNoticeVersion=BidNoticeVersion, PreflightCase=PreflightCase)
module('analysis_models', QualificationAnalysisRun=QualificationAnalysisRun,
       QualificationRequirementRecord=QualificationRequirementRecord, QualificationEvidenceRecord=QualificationEvidenceRecord)
module('judgment_models', CompanyQualificationProfileCompleteness=CompanyQualificationProfileCompleteness,
       QualificationJudgmentRun=QualificationJudgmentRun)
module('qualification.rules.judgment', RULE_VERSION='qualification-rules-v0.3')

class JudgmentError(ValueError):
    def __init__(self, code, message, status_code=409): self.code=code; self.message=message; self.status_code=status_code
class ApiError(Exception):
    def __init__(self, status_code, code, message): self.status_code=status_code; self.code=code; self.message=message
PROFILES = {}
def load_company(db, key):
    if key not in PROFILES: raise JudgmentError('COMPANY_NOT_FOUND','회사가 없습니다.',404)
    return PROFILES[key]
def snapshot(company, completeness): return types.SimpleNamespace(model_dump=lambda **_: company)
module('qualification.judgment', QualificationJudgmentError=JudgmentError, _load_company=load_company,
       _record_to_completeness=lambda value: None, build_company_profile_snapshot=snapshot)
module('errors', ApiError=ApiError)
def auth(user, company_id):
    if company_id == OTHER: raise ApiError(403, 'FORBIDDEN', '권한이 없습니다.')
module('auth', authorize_company_access=auth, authorize_case_access=lambda *args: None,
       get_optional_current_user=lambda: None)
module('auth_models', AppUser=object)
def get_db(): raise AssertionError('override get_db')
module('database', get_db=get_db)
contract = importlib.import_module(f'{PKG}.qualification.state_contract')
service = importlib.import_module(f'{PKG}.qualification.state_service')
catalog = importlib.import_module(f'{PKG}.qualification.notice_catalog')
router_module = importlib.import_module(f'{PKG}.qualification.routers.catalog')
state_router_module = importlib.import_module(f'{PKG}.qualification.routers.state')


@pytest.fixture
def db():
    PROFILES.clear(); PROFILES[COMPANY]={'company_id':str(COMPANY),'industries':['1450'],'private':'DO_NOT_EXPOSE_COMPANY'}
    PROFILES[OTHER]={'company_id':str(OTHER)}
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session: yield session
    engine.dispose()


def seed(db, n=1, company=COMPANY, result='eligible', analysis_status='SUCCEEDED', case=True, analysis=True, judgment=True, business='SERVICE', serial=''):
    rows=[]
    for i in range(n):
        name=f'{serial}-{i}'; notice_id=uid('notice'+name); vid=uid('version'+name); cid=uid('case'+name+str(company)); aid=uid('analysis'+name); jid=uid('judgment'+name+str(company))
        notice=BidNotice(id=notice_id,bid_notice_no=f'R-{name}',title=f'공고 {name}',business_type=business,last_seen_at=NOW-timedelta(minutes=i))
        version=BidNoticeVersion(id=vid,notice_id=notice_id,version_number=1,is_current=True)
        db.add_all([notice,version])
        if case: db.add(PreflightCase(id=cid,notice_id=notice_id,current_version_id=vid,company_id=company,created_at=NOW))
        if analysis:
            ar=QualificationAnalysisRun(id=aid,notice_version_id=vid,created_at=NOW,status=analysis_status)
            ar.requirements=[QualificationRequirementRecord(id=uid('req'+name),requirement_key='REQ-1',evidence_keys=['E1'])]
            ar.evidence=[QualificationEvidenceRecord(id=uid('ev'+name),evidence_key='E1',notice_version_id=str(vid))]
            db.add(ar)
        if judgment and case and analysis:
            jr=QualificationJudgmentRun(id=jid,preflight_case_id=cid,company_id=company,notice_version_id=vid,analysis_run_id=aid,
               created_at=NOW,analysis_status=analysis_status,reference_date=DAY,profile_snapshot=PROFILES[company],overall_status=result)
            jr.judgments=[QualificationJudgmentRecord(id=uid('jrec'+name+str(company)),requirement_key='REQ-1',status='UNKNOWN' if result=='insufficient_data' else 'SATISFIED' if result=='eligible' else 'UNSATISFIED',unknown_reason='profile_missing' if result=='insufficient_data' else None,rule_version='qualification-rules-v0.3',requirement_evidence_keys=['E1'])]
            db.add(jr)
        rows.append((notice_id,vid,cid,aid,jid))
    db.commit(); return rows


def read(db, **kw): return catalog.read_notice_catalog(db, company_id=COMPANY, **kw)

@pytest.mark.parametrize('result', ['eligible','ineligible','insufficient_data'])
def test_stored_status_buckets(db,result):
    seed(db,result=result); data=read(db)
    assert data['status_counts'][result]==1
    assert data['items'][0]['state']['display_state']=='RESULT_AVAILABLE'
    assert data['items'][0]['state']['coverage_state']=='UNVERIFIED'
    assert data['full_notice_eligibility_asserted'] is False

@pytest.mark.parametrize('case,analysis,judgment,expected', [(False,False,False,'unreviewed'),(False,True,False,'unreviewed'),(True,False,False,'unreviewed'),(True,True,False,'insufficient_data')])
def test_missing_stage_is_not_missing_query(db,case,analysis,judgment,expected):
    seed(db,case=case,analysis=analysis,judgment=judgment)
    assert read(db)['items'][0]['status_bucket']==expected

@pytest.mark.parametrize('status',['FAILED','PARTIAL'])
def test_bad_analysis_does_not_keep_eligible_bucket(db,status):
    seed(db,analysis_status=status); item=read(db)['items'][0]
    assert item['status_bucket']=='insufficient_data'
    assert item['state']['display_state'] in {'ANALYSIS_FAILED','ANALYSIS_INCOMPLETE'}


def test_filter_and_facets_work_beyond_first_100(db):
    seed(db,120,result='ineligible')
    seed(db,1,result='eligible',business='CONSTRUCTION',serial='target')
    data=read(db,status='eligible',limit=10)
    assert data['total']==1 and data['scope_total']==121 and data['items'][0]['business_type']=='CONSTRUCTION'
    assert data['status_counts']['ineligible']==120
    assert data['business_counts']['CONSTRUCTION']==1
    assert read(db,business_type='CONSTRUCTION')['total']==1


def test_pagination_full_range_and_stable_order(db):
    seed(db,45)
    ids=[]
    hashes=set()
    for offset in (0,20,40):
        data=read(db,offset=offset);ids.extend(x['id'] for x in data['items']);hashes.add(data['scope_sha256'])
        assert data['status_counts']['eligible']==45
    assert len(ids)==len(set(ids))==45 and len(hashes)==1


def test_literal_query_does_not_treat_percent_as_wildcard(db):
    ids=seed(db,3)
    db.get(BidNotice,ids[1][0]).title='100% 자료'; db.commit()
    assert read(db,q='%')['total']==1
    assert read(db,q='_')['total']==0

@pytest.mark.parametrize('field,value',[('title','찾을제목'),('bid_notice_no','고유번호'),('announcing_institution_name','발주처'),('demanding_institution_name','수요처')])
def test_search_fields(db,field,value):
    ids=seed(db);setattr(db.get(BidNotice,ids[0][0]),field,value);db.commit()
    assert read(db,q=' '+value+' ')['query_total']==1


def test_types_all_exist_even_when_page_has_only_service(db):
    seed(db,25)
    seed(db,1,business='FOREIGN',serial='foreign')
    data=read(db,limit=1)
    assert sum(data['business_counts'].values())==26 and data['business_counts']['FOREIGN']==1


def test_other_company_case_is_not_selected(db):
    seed(db,company=OTHER)
    data=read(db)
    assert data['items'][0]['case_id'] is None
    assert data['status_counts']['unreviewed']==1
    assert str(OTHER) not in json.dumps(data)


def test_no_company_does_not_read_private_state(db):
    seed(db)
    data=catalog.read_notice_catalog(db)
    assert data['company_id'] is None and data['items'][0]['state'] is None
    assert str(COMPANY) not in json.dumps(data)


def test_profile_change_returns_rejudgment(db):
    seed(db);PROFILES[COMPANY]={**PROFILES[COMPANY],'industries':['1227']}
    state=read(db)['items'][0]['state']
    assert state['display_state']=='REJUDGMENT_REQUIRED'
    assert state['selected_judgment_run_id'] is None
    assert state['stored_overall_status']=='eligible'


def test_reference_date_change(db):
    seed(db)
    assert read(db,reference_date=DAY+timedelta(days=1))['items'][0]['state']['display_state']=='REJUDGMENT_REQUIRED'


def test_uses_latest_analysis_not_latest_judgment(db):
    row=seed(db)[0]
    db.add(QualificationAnalysisRun(id=uid('new'),notice_version_id=row[1],created_at=NOW+timedelta(seconds=1),status='FAILED'));db.commit()
    item=read(db)['items'][0]
    assert item['status_bucket']=='insufficient_data' and item['state']['display_state']=='ANALYSIS_FAILED'


def test_wrong_rule_requires_rejudgment(db):
    row=seed(db)[0];db.get(QualificationJudgmentRun,row[4]).rule_version='old';db.commit()
    assert read(db)['items'][0]['state']['display_state']=='REJUDGMENT_REQUIRED'


def test_bad_row_is_visible_not_dropped_or_unreviewed(db):
    rows=seed(db,2)
    db.get(QualificationAnalysisRun,rows[0][3]).diagnostics={'bad':True};db.commit()
    data=read(db)
    assert data['total']==2 and data['status_counts']['eligible']==1 and data['status_counts']['insufficient_data']==1
    assert any(item['state']['display_state']=='DATA_INVALID' for item in data['items'])


def test_catalog_and_detail_use_same_state_contract(db):
    row=seed(db)[0]
    assert read(db)['items'][0]['state']==service.read_qualification_state(db,case_id=row[2]).to_dict()


def test_latest_case_policy_and_company_scope(db):
    row=seed(db)[0]
    newer=PreflightCase(id=uid('newer-case'),notice_id=row[0],current_version_id=row[1],company_id=COMPANY,created_at=NOW+timedelta(seconds=1))
    db.add(newer);db.commit()
    item=read(db)['items'][0]
    assert item['case_id']==str(newer.id) and item['state']['display_state']=='JUDGMENT_REQUIRED'


def test_raw_profile_and_quotes_not_exposed(db):
    seed(db)
    content=json.dumps(read(db))
    assert 'PRIVATE_SOURCE' not in content and 'PRIVATE_QUOTE' not in content and 'DO_NOT_EXPOSE_COMPANY' not in content


def test_no_writes_or_pending_flush(db):
    row=seed(db)[0]
    db.add(BidNotice(id=uid('pending'),bid_notice_no='P',title='pending',business_type='SERVICE',last_seen_at=NOW))
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany): statements.append(statement.lstrip().upper())
    event.listen(db.bind,'before_cursor_execute',capture)
    try: assert read(db)['total']==1
    finally: event.remove(db.bind,'before_cursor_execute',capture)
    assert not any(s.startswith(('INSERT','UPDATE','DELETE')) for s in statements)


def test_query_count_not_n_plus_one(db):
    seed(db,120)
    queries=[]
    def capture(conn,cursor,statement,parameters,context,executemany): queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',capture)
    try: read(db,limit=5)
    finally: event.remove(db.bind,'before_cursor_execute',capture)
    assert len(queries) < 20, len(queries)
    assert not any('qualification_evidence.quote' in s for s in queries)
    assert not any('qualification_requirements.raw' in s for s in queries)

@pytest.mark.parametrize('kw',[{'limit':0},{'limit':101},{'offset':-1},{'limit':True},{'business_type':'FAKE'},{'status':'FAKE'},{'q':'a'*201},{'reference_date':datetime.now()}])
def test_bad_parameters_rejected(db,kw):
    with pytest.raises(ValueError): read(db,**kw)


def test_large_scope_is_explicit_error_not_truncated(db,monkeypatch):
    seed(db,3);monkeypatch.setattr(catalog,'MAX_SCOPE_ROWS',2)
    with pytest.raises(contract.StateInputError,match='CATALOG_SCOPE_TOO_LARGE'): read(db)


def test_analysis_changed_mid_read(db,monkeypatch):
    row=seed(db)[0]
    original=catalog._judgments
    def changed(*args):
        found=original(*args)
        db.add(QualificationAnalysisRun(id=uid('changed'),notice_version_id=row[1],created_at=NOW+timedelta(seconds=1),status='FAILED'));db.flush()
        return found
    monkeypatch.setattr(catalog,'_judgments',changed)
    with pytest.raises(contract.StateInputError,match='STATE_BASIS_CHANGED'): read(db)


def client(db):
    app=FastAPI();app.include_router(state_router_module.router,prefix='/api/v1')
    app.dependency_overrides[get_db]=lambda: db
    @app.exception_handler(ApiError)
    async def error_handler(request,error):
        return JSONResponse({'error':{'code':error.code,'message':error.message}},status_code=error.status_code)
    return TestClient(app)


def test_http_path_and_serialization(db):
    seed(db)
    response=client(db).get('/api/v1/qualification-notice-catalog',params={'company_id':str(COMPANY)})
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['state']['stored_reference_date']=='2026-09-15'


def test_http_company_authorization(db):
    seed(db,company=OTHER)
    response=client(db).get('/api/v1/qualification-notice-catalog',params={'company_id':str(OTHER)})
    assert response.status_code==403

@pytest.mark.parametrize('params',[{'company_id':'bad'},{'limit':101},{'offset':-1},{'status':'bad'},{'business_type':'bad'},{'reference_date':'bad'}])
def test_http_validation(db,params):
    assert client(db).get('/api/v1/qualification-notice-catalog',params=params).status_code==422


def test_http_database_failure_not_empty_success(db,monkeypatch):
    from sqlalchemy.exc import OperationalError
    def fail(*a,**k): raise OperationalError('PRIVATE_SQL',{},Exception('PRIVATE_DB_ADDRESS'))
    monkeypatch.setattr(router_module,'read_notice_catalog',fail)
    response=client(db).get('/api/v1/qualification-notice-catalog')
    assert response.status_code==503 and 'PRIVATE' not in response.text


def test_http_scope_size_error(db,monkeypatch):
    seed(db,3);monkeypatch.setattr(catalog,'MAX_SCOPE_ROWS',2)
    assert client(db).get('/api/v1/qualification-notice-catalog').status_code==422


def test_http_missing_company_is_404(db):
    assert client(db).get('/api/v1/qualification-notice-catalog',params={'company_id':str(uid('missing'))}).status_code==404
