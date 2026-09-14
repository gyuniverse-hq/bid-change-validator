"""구/신 실제 파이프라인을 실행하되 모델 I/O는 합성 응답으로 대체한다.
DB 검증은 전용 로컬 qualification_test PostgreSQL에서만 수행한다.
"""
import importlib.util
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import uuid4
from types import SimpleNamespace

import pytest

from apps.api.app.scripts import check_qualification_repeatability as probe
from apps.api.app.ai.qualification.extraction.analysis_pipeline import QualificationAnalysisInput
from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot

TEXT = '3. 참가자격\n서울특별시에 소재한 업체'
DAY = date(2026, 9, 15)


def captured():
    source = QualificationAnalysisInput(notice_id='notice', notice_version_id='version', documents=[{
        'document_id':'doc','file_sha256':'a'*64,'extracted_text_sha256':'b'*64,
        'extracted_blocks':[{'block_index':0,'page':1,'text':TEXT}]}])
    profile = CompanyProfileSnapshot(company_id='company', region_name='서울특별시')
    return probe.CapturedCase('case', 'QA-NOT-LIVE', profile, ({'role':'current','input':source,
        'input_sha256':probe.digest(source.model_dump(mode='json')),'notice_date':None},))


class Model:
    model = 'synthetic-no-network'
    def __init__(self): self.bodies=[]
    def __call__(self,prompt,body,schema):
        self.bodies.append(body)
        if schema['name']=='eligibility_slots':
            fields=schema['schema']['properties']['requirements']['items']['properties']
            return {'requirements':[{**{name:None for name in fields},'유형':'지역요건','raw':'서울특별시에 소재한 업체','지역_raw':'서울특별시'}]}
        payload=json.loads(body); decisions=[]
        for key in payload['target_candidate_ids']:
            if schema['name']=='qualification_review_v1':
                decisions.append({'candidate_id':key,'status':'REQUIREMENT','reason':None,'slots':[{
                    'type':'지역요건','basis':'SELF_CONTAINED','fields':[{
                        'name':'지역_raw','source_candidate_id':key,'quote':'서울특별시'}]}]})
            else:
                src=lambda quote:{'source_candidate_id':key,'quote':quote}
                decisions.append({'candidate_id':key,'status':'REQUIREMENT','reason':None,
                    'basis':'SELF_CONTAINED','role':'mandatory','atoms':[{'atom_id':'a','type':'REGION',
                    'subject':'BIDDER','predicate_source':src(TEXT),'value_role':'REGION_NAME','value_source':src('서울특별시'),
                    'qualifiers':[],'aggregation':'UNSPECIFIED','aggregation_source':None}],
                    'nodes':[{'node_id':'root','operator':'ATOM','atom_id':'a','children':[],'evidence':[]}],'root_id':'root'})
        return {'decisions':decisions}


def test_actual_three_strategies_and_rules_with_frozen_source():
    fixture=captured(); before=fixture.versions[0]['input'].model_dump(mode='json')
    model=Model(); executor=probe.BudgetedExtractor(model,20)
    result=probe.measure(fixture,reference_date=DAY,extractor=executor,runs=2)
    assert len(result['rows'])==6
    assert all(row['execution']=='RETURNED' for row in result['rows']),result['rows']
    assert all(row['requirement_count']==1 for row in result['rows']),result['rows']
    assert all(item['same_semantics'] and item['same_judgments'] for item in result['summary'])
    assert result['quality_verdict']=='NOT_ESTABLISHED' and result['db_writes'] is False
    assert all(item['accuracy'] is None for item in result['summary'])
    assert all(row['notice_overall_status'] is None for row in result['rows'] if row['strategy']=='review_graph_v1')
    assert fixture.versions[0]['input'].model_dump(mode='json')==before
    assert TEXT not in json.dumps(result,ensure_ascii=False)
    assert all('"company_id"' not in body for body in model.bodies)


def test_budget_never_calls_provider_after_limit():
    calls=[];wrapped=probe.BudgetedExtractor(lambda *args:calls.append(args) or {},1)
    wrapped('prompt','body',{})
    with pytest.raises(probe.ProbeError,match='BUDGET_EXHAUSTED'):wrapped('p','b',{})
    assert len(calls)==wrapped.calls==1


@pytest.mark.parametrize('limit',[True,0,-1,201,1.5])
def test_bad_budget_rejected(limit):
    with pytest.raises(probe.ProbeError):probe.BudgetedExtractor(lambda *x:{},limit)


def test_call_error_report_never_includes_exception_or_source():
    def fail(*args):raise RuntimeError('PRIVATE_KEY_AND_SOURCE')
    wrapper=probe.BudgetedExtractor(fail,2)
    with pytest.raises(RuntimeError):wrapper('PRIVATE_PROMPT','PRIVATE_SOURCE',{})
    assert 'PRIVATE' not in json.dumps(wrapper.events)
    assert wrapper.events[0]['status']=='ERROR'


@pytest.mark.parametrize('change',[{'operator':'>='},{'period_months':36},{'scope':{'restriction':'EXCLUDE'}}])
def test_semantic_signature_includes_operator_period_scope(change):
    req=QualificationRequirement(requirement_key='a',notice_version_id='v',type='REGION',operator='MATCH',value='지역',raw='지역')
    assert probe.canonical_signature([req])!=probe.canonical_signature([req.model_copy(update=change)])


def test_signature_ignores_display_ids_but_keeps_group_links():
    def req(key,group,val):return QualificationRequirement(requirement_key=key,requirement_group_key=group,group_operator='ANY_OF',notice_version_id='v',type='INDUSTRY',operator='MATCH',value=val,raw=val)
    a=[req('a1','g1','1257'),req('b','g1','1227'),req('a2','g2','1257'),req('c','g2','6786')]
    b=[item.model_copy(update={'requirement_key':'new'+item.requirement_key,'requirement_group_key':'new'+item.requirement_group_key}) for item in reversed(a)]
    assert probe.canonical_signature(a)==probe.canonical_signature(b)
    assert probe.canonical_signature(a)!=probe.canonical_signature(a[:2]+a[3:])


def test_output_does_not_overwrite_previous_run(tmp_path):
    path=tmp_path/'report.json';probe.emit({'mode':'CAPTURE_ONLY'},path)
    with pytest.raises(FileExistsError):probe.emit({'mode':'OTHER'},path)
    assert json.loads(path.read_text())['mode']=='CAPTURE_ONLY'


def test_wrong_database_dialect_rejected_before_connecting():
    with pytest.raises(probe.ProbeError,match='READ_ONLY_REQUIRED'):
        probe.capture_case(SimpleNamespace(dialect=SimpleNamespace(name='sqlite')),uuid4(),'target')


@pytest.fixture
def dedicated_database_case():
    if importlib.util.find_spec('psycopg') is None:pytest.skip('PostgreSQL driver not available')
    from apps.api.app.database import engine,SessionLocal
    if engine.url.host not in {'localhost','127.0.0.1'} or engine.url.database!='qualification_test':
        pytest.skip('requires disposable localhost qualification_test database')
    from apps.api.app.models import Company,BidNotice,BidNoticeVersion,NoticeDocument,PreflightCase
    company_id,notice_id,case_id=uuid4(),uuid4(),uuid4();v1id,v2id=uuid4(),uuid4()
    notice_number='QA-READONLY-'+uuid4().hex[:12]
    with SessionLocal() as db:
        db.add(Company(id=company_id,name='SYNTHETIC PRIVATE COMPANY',region_name='서울특별시',company_size='SMALL'))
        db.add(BidNotice(id=notice_id,bid_notice_no=notice_number,title='합성 읽기전용 검증',business_type='SERVICE',first_seen_at=datetime.now(timezone.utc),last_seen_at=datetime.now(timezone.utc)))
        db.flush()
        for n,vid in [(1,v1id),(2,v2id)]:
            db.add(BidNoticeVersion(id=vid,notice_id=notice_id,version_number=n,bid_notice_order=f'{n-1:03}',
                is_current=n==2,source_endpoint='test',payload_hash=str(n)*64,raw_json={},collected_at=datetime.now(timezone.utc)))
            db.flush()
            db.add(NoticeDocument(id=uuid4(),notice_version_id=vid,document_order=0,name='합성 원문',
                url='https://example.invalid/source',source_field='test',extraction_status='EXTRACTED',
                extracted_blocks=[{'block_index':0,'page':1,'text':TEXT}],file_sha256='a'*64,extracted_text_sha256='b'*64))
        db.flush()
        db.add(PreflightCase(id=case_id,company_id=company_id,notice_id=notice_id,baseline_version_id=v1id,current_version_id=v2id,title='합성 검토',status='READY'))
        db.commit()
    try:yield engine,case_id,notice_number,company_id
    finally:
        with SessionLocal() as db:
            db.delete(db.get(BidNotice,notice_id));db.commit()
            db.delete(db.get(Company,company_id));db.commit()


def test_capture_reads_real_postgresql_snapshot_without_changes(dedicated_database_case):
    engine,cid,no,_=dedicated_database_case
    result=probe.capture_case(engine,cid,no)
    assert [v['role'] for v in result.versions]==['baseline','current']
    assert [v['version_number'] for v in result.versions]==[1,2]
    assert all(v['extracted_document_count']==1 for v in result.versions)
    assert TEXT not in json.dumps(result.manifest(),ensure_ascii=False)
    assert 'PRIVATE COMPANY' not in json.dumps(result.manifest(),ensure_ascii=False)


def test_capture_target_mismatch_refuses_other_notice(dedicated_database_case):
    engine,cid,_,_=dedicated_database_case
    with pytest.raises(probe.ProbeError,match='NOTICE_TARGET_MISMATCH'):probe.capture_case(engine,cid,'WRONG')


def test_postgres_actually_blocks_an_accidental_write(dedicated_database_case,monkeypatch):
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError
    from apps.api.app.models import Company
    from apps.api.app.database import SessionLocal
    from apps.api.app.qualification import judgment
    engine,cid,no,company_id=dedicated_database_case
    def unwanted_write(db, key):db.execute(update(Company).where(Company.id==key).values(name='SHOULD_NOT_CHANGE'))
    monkeypatch.setattr(judgment,'_load_company',unwanted_write)
    with pytest.raises(DBAPIError):probe.capture_case(engine,cid,no)
    with SessionLocal() as db:assert db.get(Company,company_id).name=='SYNTHETIC PRIVATE COMPANY'
