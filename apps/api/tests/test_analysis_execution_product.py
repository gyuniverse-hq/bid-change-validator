"""새 경로의 실제 분석 서비스/HTTP/저장 계약 검증. 모델 통신만 대역.

전용 로컬 PostgreSQL DB에서만 저장 테스트를 수행한다. 정답/실모델 성능 테스트가 아니다.
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from apps.api.app.analysis_schemas import QualificationAnalysisRequest
from apps.api.app.config import get_settings
from apps.api.app.qualification import analysis as service
from apps.api.app.qualification.analysis_execution import execution_metadata, source_basis, EXECUTION_CODE, EXECUTION_VERSION
from apps.api.app.qualification.routers import analysis as routes
from apps.api.app.errors import ApiError
from apps.api.tests.test_qualification_repeatability_probe import Model, captured, dedicated_database_case


@pytest.fixture
def enable_review(monkeypatch):
    monkeypatch.setattr(get_settings(), 'qualification_review_v1_enabled', True)


def fake_version(source):
    doc = source.documents[0]
    return SimpleNamespace(id=source.notice_version_id, notice_id=source.notice_id, documents=[SimpleNamespace(
        id=doc.document_id, file_sha256=doc.file_sha256, extracted_text_sha256=doc.extracted_text_sha256,
        extraction_status='EXTRACTED', extracted_blocks=doc.extracted_blocks)])


def service_harness(monkeypatch):
    source = captured().versions[0]['input']
    version = fake_version(source)
    monkeypatch.setattr(service, '_load_notice_version', lambda *a, **k: version)
    saved = []
    monkeypatch.setattr(service, '_persist_result', lambda db, **kw: saved.append(kw['result']) or kw['result'])
    return source, version, saved


def test_real_review_pipeline_metadata_roundtrip(monkeypatch, enable_review):
    source, version, saved = service_harness(monkeypatch)
    model = Model()
    result = service.run_qualification_analysis(None, notice_id=source.notice_id, version_number=1,
        structured_extract=model, extraction_strategy='review_v1')
    assert result.status == 'SUCCEEDED'
    assert result.requirements[0].type == 'REGION'
    assert result.requirements[0].value == '서울특별시'
    details = execution_metadata([d.model_dump(mode='json') for d in result.diagnostics])
    assert details['strategy'] == 'review_v1'
    assert details['max_calls'] == 24
    assert len(saved) == 1
    assert any(d.code == 'REVIEW_EXECUTION_AUDIT' for d in result.diagnostics)
    assert len(model.bodies) >= 1
    assert 'company_id' not in ''.join(model.bodies)


def test_missing_document_cannot_be_succeeded(monkeypatch, enable_review):
    source, version, saved = service_harness(monkeypatch)
    version.documents.append(SimpleNamespace(id='missing', file_sha256=None, extracted_text_sha256=None,
        extraction_status='FAILED', extracted_blocks=None))
    result = service.run_qualification_analysis(None, notice_id=source.notice_id, version_number=1,
        structured_extract=Model(), extraction_strategy='review_v1')
    assert result.status == 'PARTIAL'
    assert any(d.code == 'DOCUMENT_INPUT_INCOMPLETE' for d in result.diagnostics)
    assert execution_metadata([d.model_dump(mode='json') for d in result.diagnostics])['omitted_document_ids'] == ['missing']


def test_source_changed_during_llm_is_not_saved(monkeypatch, enable_review):
    source, version, saved = service_harness(monkeypatch)
    model = Model()
    def mutate(*args):
        answer = model(*args)
        version.documents[0].extracted_blocks = [{'block_index': 0, 'text':'수정된 다른 조건'}]
        return answer
    with pytest.raises(service.QualificationAnalysisError) as caught:
        service.run_qualification_analysis(None, notice_id=source.notice_id, version_number=1,
            structured_extract=mutate, extraction_strategy='review_v1')
    assert caught.value.code == 'ANALYSIS_SOURCE_CHANGED'
    assert not saved


def test_legacy_remains_default_with_recorded_provenance(monkeypatch):
    source, version, saved = service_harness(monkeypatch)
    model = Model()
    result = service.run_qualification_analysis(None, notice_id=source.notice_id, version_number=1, structured_extract=model)
    assert result.requirements
    assert execution_metadata([d.model_dump(mode='json') for d in result.diagnostics])['strategy'] == 'legacy'
    assert not any(d.code == 'REVIEW_EXECUTION_AUDIT' for d in result.diagnostics)


def test_disabled_before_provider_or_database(monkeypatch):
    monkeypatch.setattr(get_settings(), 'qualification_review_v1_enabled', False)
    def unexpected(*a, **k): raise AssertionError('must not call')
    monkeypatch.setattr(service, '_load_notice_version', unexpected)
    with pytest.raises(service.QualificationAnalysisError, match='활성화'):
        service.run_qualification_analysis(None, notice_id=uuid4(), version_number=1,
            structured_extract=unexpected, extraction_strategy='review_v1')


@pytest.mark.parametrize('body', [{'extraction_strategy':'review_graph_v1'}, {'extraction_strategy':'typo'},
    {'extraction_strategy':'review_v1','max_calls':100000}, {'extraction_strategy':None}])
def test_request_does_not_accept_unknown_mode_or_client_budget(body):
    with pytest.raises(ValidationError): QualificationAnalysisRequest.model_validate(body)


def test_legacy_without_body_is_preserved():
    assert QualificationAnalysisRequest().extraction_strategy == 'legacy'


def test_old_metadata_not_inferred():
    assert execution_metadata([]) is None
    assert execution_metadata([{'code':EXECUTION_CODE,'details':{'version':'bad'}}]) is None
    good = {'code':EXECUTION_CODE,'details':{'version':EXECUTION_VERSION,'strategy':'review_v1','input_sha256':'a'*64,'source_sha256':'b'*64}}
    assert execution_metadata([good])['strategy'] == 'review_v1'
    assert execution_metadata([good,good]) is None


def make_client(db=None):
    app=FastAPI();app.include_router(routes.router)
    app.dependency_overrides[routes.get_db] = lambda: db
    @app.exception_handler(ApiError)
    async def error_handler(request,error):
        return JSONResponse({'error':{'code':error.code,'message':error.message}},status_code=error.status_code)
    return TestClient(app)


def test_http_disabled_does_not_call_model(monkeypatch):
    monkeypatch.setattr(get_settings(), 'qualification_review_v1_enabled', False)
    monkeypatch.setattr(routes,'OpenAIStructuredExtractor',lambda *a,**k:pytest.fail('called provider'))
    response=make_client().post(f'/api/v1/notices/{uuid4()}/versions/1/qualification-analysis',json={'extraction_strategy':'review_v1'})
    assert response.status_code==409 and response.json()['error']['code']=='EXTRACTION_STRATEGY_DISABLED'


def test_options_are_read_only_and_match_gate(monkeypatch):
    monkeypatch.setattr(routes,'OpenAIStructuredExtractor',lambda *a,**k:pytest.fail('called provider'))
    for enabled in [False,True]:
        monkeypatch.setattr(get_settings(),'qualification_review_v1_enabled',enabled)
        response=make_client().get('/api/v1/qualification-analysis-options')
        assert response.status_code==200
        assert response.json()['strategies'][1]['enabled'] is enabled
        assert response.json()['graph_product_enabled'] is False


def test_budgeted_provider_does_not_retry(monkeypatch):
    import sys
    observed={}
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=lambda **kwargs: observed.update(kwargs)))
    routes.review_client_factory('test-only')
    assert observed=={'api_key':'test-only','timeout':60.0,'max_retries':0}


def test_real_postgresql_api_save_reload_and_judge(dedicated_database_case, enable_review, monkeypatch):
    from apps.api.app.database import SessionLocal
    from apps.api.app.models import PreflightCase
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.qualification.state_service import read_qualification_state
    from apps.api.app.qualification.notice_catalog import read_notice_catalog
    engine,cid,no,company_id=dedicated_database_case
    model=Model();model.available=True
    monkeypatch.setattr(routes,'OpenAIStructuredExtractor',lambda **kwargs:model)
    with SessionLocal() as db:
        case=db.get(PreflightCase,cid)
        path=f'/api/v1/notices/{case.notice_id}/versions/2/qualification-analysis'
        client=make_client(db)
        response=client.post(path,json={'extraction_strategy':'review_v1'})
        assert response.status_code==201,response.text
        body=response.json()
        assert body['extraction_strategy']=='review_v1'
        assert body['execution_basis']['strategy']=='review_v1'
        loaded=client.get(f"/api/v1/qualification-analyses/{body['id']}").json()
        assert loaded==body
        assert any(d['code']=='REVIEW_EXECUTION_AUDIT' for d in loaded['diagnostics'])
        from datetime import date
        from uuid import UUID
        run=run_targeted_qualification_judgment(db,case_id=cid,analysis_run_id=UUID(body['id']),reference_date=date(2026,9,15))
        selected=read_qualification_state(db,case_id=cid)
        assert selected.selected_judgment_run_id==str(run.id)
        listing=read_notice_catalog(db,company_id=company_id,q=no)
        assert listing['items'][0]['state']==selected.to_dict()
        assert run.overall_status=='eligible'
        # 독립 실행은 이전 저장을 덮지 않으며 회사 재판정은 이력의 분석 ID를 그대로 쓴다.
        second=client.post(path,json={'extraction_strategy':'legacy'})
        assert second.status_code==201 and second.json()['id']!=body['id']
        assert client.get(f"/api/v1/qualification-analyses/{body['id']}").json()['extraction_strategy']=='review_v1'
