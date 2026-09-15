"""일회용 PostgreSQL + 실제 API/ORM/판정기. 모델 I/O만 합성 대역이다."""
import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, func

from apps.api.app.config import get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.main import app
from apps.api.app.models import NoticeDocument, Company
from apps.api.app.analysis_models import QualificationAnalysisRun
from apps.api.app.qualification.graph.models import QualificationGraphRun
from apps.api.app.qualification.graph import service
from apps.api.app.qualification.routers import graph as routes
from apps.api.tests.test_qualification_repeatability_probe import dedicated_database_case
from apps.api.tests.test_document_graph_comparison import GraphModel

DAY = date(2026,9,15)


@pytest.fixture
def graph_case(dedicated_database_case, monkeypatch):
    engine,cid,no,company_id = dedicated_database_case
    monkeypatch.setattr(get_settings(), 'qualification_graph_enabled', True)
    model=GraphModel(); model.available=True
    monkeypatch.setattr(routes, 'OpenAIStructuredExtractor', lambda **kwargs:model)
    yield engine,cid,no,company_id,model
    app.dependency_overrides.pop(routes.get_optional_current_user, None)


def path(cid): return f'/api/v1/preflight-cases/{cid}'


def create(client,cid,role='current'):
    response=client.post(path(cid)+'/qualification-graphs',json={'version_role':role})
    assert response.status_code==201,response.text
    return response.json()


def test_actual_analysis_storage_read_judgment_compare(graph_case):
    _,cid,_,company_id,model=graph_case
    with TestClient(app) as client:
        b=create(client,cid,'baseline'); c=create(client,cid)
        assert b['status']=='SUCCEEDED' and b['id']!=c['id']
        read=client.get(path(cid)+f"/qualification-graphs/{c['id']}")
        assert read.status_code==200 and read.json()['snapshot']==c['snapshot']
        assert 'profile_snapshot' not in json.dumps(c['snapshot'])
        calls=len(model.calls)
        judged=client.post(path(cid)+'/qualification-graph-judgments',json={'graph_run_id':c['id'],'reference_date':str(DAY)})
        assert judged.status_code==201,judged.text
        assert judged.json()['result']['company_id']==str(company_id)
        assert judged.json()['result']['overall_status']=='eligible'
        again=client.get(path(cid)+f"/qualification-graph-judgments/{judged.json()['id']}")
        assert again.status_code==200 and again.json()['result']==judged.json()['result']
        r=client.get(path(cid)+'/qualification-graphs/compare',params={'baseline_run_id':b['id'],'current_run_id':c['id']})
        assert r.status_code==200,r.text
        assert r.json()['counts']=={'UNCHANGED':1}
        assert r.json()['db_writes'] is False and r.json()['eligibility_change_asserted'] is False
        assert len(model.calls)==calls
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(QualificationAnalysisRun).where(QualificationAnalysisRun.notice_version_id.in_([b['notice_version_id'],c['notice_version_id']])))==0


def test_changed_source_is_modified(graph_case):
    _,cid,_,_,_=graph_case
    with SessionLocal() as db:
        case=service._case(db,cid)
        document=db.scalar(select(NoticeDocument).where(NoticeDocument.notice_version_id==case.current_version_id))
        document.extracted_blocks=[{'block_index':0,'page':1,'text':'3. 참가자격\n부산광역시에 소재한 업체'}]
        db.commit()
    with TestClient(app) as client:
        b=create(client,cid,'baseline');c=create(client,cid)
        r=client.get(path(cid)+'/qualification-graphs/compare',params={'baseline_run_id':b['id'],'current_run_id':c['id']})
        assert r.status_code==200,r.text
        assert r.json()['counts']=={'MODIFIED':1},r.text
        assert r.json()['changes'][0]['before']['meaning']['predicates'][0]['value']=='서울특별시'
        assert r.json()['changes'][0]['after']['meaning']['predicates'][0]['value']=='부산광역시'


def test_repeated_analysis_is_not_notice_change(graph_case):
    _,cid,_,_,model=graph_case
    with TestClient(app) as client:
        a=create(client,cid);model.non_requirement='서울';b=create(client,cid)
        r=client.get(path(cid)+'/qualification-graphs/compare',params={'baseline_run_id':a['id'],'current_run_id':b['id']})
        assert r.status_code==200,r.text
        assert r.json()['mode']=='REPEATED_ANALYSIS'
        assert r.json()['counts']=={'ANALYSIS_INCONSISTENCY':1}


def test_comparison_does_not_execute_sql_writes(graph_case):
    engine,cid,*_=graph_case
    with TestClient(app) as client:
        a=create(client,cid,'baseline');b=create(client,cid);statements=[]
        def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement.lstrip().upper())
        event.listen(engine,'before_cursor_execute',capture)
        try:
            r=client.get(path(cid)+'/qualification-graphs/compare',params={'baseline_run_id':a['id'],'current_run_id':b['id']})
            assert r.status_code==200,r.text
        finally:event.remove(engine,'before_cursor_execute',capture)
        assert not any(s.startswith(('INSERT','UPDATE','DELETE')) for s in statements)


def test_company_edit_rejudges_same_graph_without_model(graph_case):
    _,cid,_,company_id,model=graph_case
    with TestClient(app) as client:
        graph=create(client,cid);calls=len(model.calls)
        payload={'graph_run_id':graph['id'],'reference_date':str(DAY)}
        first=client.post(path(cid)+'/qualification-graph-judgments',json=payload)
        assert first.status_code==201,first.text
        with SessionLocal() as db:
            db.get(Company,company_id).region_name='부산광역시';db.commit()
        second=client.post(path(cid)+'/qualification-graph-judgments',json=payload)
        assert second.status_code==201,second.text
        assert first.json()['result']['profile_sha256']!=second.json()['result']['profile_sha256']
        assert first.json()['graph_run_id']==second.json()['graph_run_id']==graph['id']
        assert len(model.calls)==calls


def test_other_company_denied(graph_case):
    _,cid,*_=graph_case
    app.dependency_overrides[routes.get_optional_current_user]=lambda:SimpleNamespace(role='MEMBER',company_id=uuid4())
    with TestClient(app) as client:
        assert client.get(path(cid)+'/qualification-graphs').status_code==403
        assert client.post(path(cid)+'/qualification-graphs',json={'version_role':'current'}).status_code==403


def test_flag_disabled_before_model(graph_case,monkeypatch):
    _,cid,_,_,model=graph_case
    monkeypatch.setattr(get_settings(),'qualification_graph_enabled',False)
    with TestClient(app) as client:
        assert client.get('/api/v1/qualification-graph-options').json()['enabled'] is False
        assert client.post(path(cid)+'/qualification-graphs',json={'version_role':'current'}).status_code==409
        assert not model.calls


@pytest.mark.parametrize('body',[{}, {'version_role':'invalid'}, {'version_role':'current','max_calls':999}])
def test_request_is_closed(graph_case,body):
    _,cid,_,_,model=graph_case
    with TestClient(app) as client:
        assert client.post(path(cid)+'/qualification-graphs',json=body).status_code==422
        assert not model.calls


def test_date_required_and_distinct_runs(graph_case):
    _,cid,*_=graph_case
    with TestClient(app) as client:
        a=create(client,cid)
        assert client.post(path(cid)+'/qualification-graph-judgments',json={'graph_run_id':a['id']}).status_code==422
        r=client.get(path(cid)+'/qualification-graphs/compare',params={'baseline_run_id':a['id'],'current_run_id':a['id']})
        assert r.status_code==409 and r.json()['error']['code']=='DISTINCT_GRAPH_RUNS_REQUIRED'


def test_reversed_version_order_is_rejected(graph_case):
    _,cid,*_=graph_case
    with TestClient(app) as client:
        a=create(client,cid,'baseline');b=create(client,cid)
        assert client.get(path(cid)+'/qualification-graphs/compare',params={'baseline_run_id':b['id'],'current_run_id':a['id']}).status_code==409


def test_tampered_saved_graph_not_returned(graph_case):
    _,cid,*_=graph_case
    with TestClient(app) as client:
        a=create(client,cid)
        with SessionLocal() as db:
            row=db.get(QualificationGraphRun,a['id']);row.payload={**row.payload,'calls':999};db.commit()
        assert client.get(path(cid)+f"/qualification-graphs/{a['id']}").status_code==409


def test_source_changed_since_save_refuses_company_judgment(graph_case):
    _,cid,*_=graph_case
    with TestClient(app) as client:
        a=create(client,cid)
        with SessionLocal() as db:
            d=db.scalar(select(NoticeDocument).where(NoticeDocument.notice_version_id==a['notice_version_id']))
            d.extracted_blocks=[{'block_index':0,'page':1,'text':'수정 원문'}];db.commit()
        r=client.post(path(cid)+'/qualification-graph-judgments',json={'graph_run_id':a['id'],'reference_date':str(DAY)})
        assert r.status_code==409 and r.json()['error']['code']=='GRAPH_SOURCE_CHANGED'


def test_new_paths_registered_in_real_openapi():
    with TestClient(app) as client:paths=client.get('/openapi.json').json()['paths']
    assert 'get' in paths['/api/v1/preflight-cases/{case_id}/qualification-graphs/compare']
    assert 'post' in paths['/api/v1/preflight-cases/{case_id}/qualification-graph-judgments']
