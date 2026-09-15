"""7-D 실제 API/PostgreSQL 저장 왕복. 일회용 테스트 DB와 합성 모델만 사용한다."""
import hashlib
import pytest
from sqlalchemy import select
from apps.api.tests.test_qualification_repeatability_probe import dedicated_database_case
from apps.api.tests.test_analysis_execution_product import make_client
from apps.api.tests.test_slot_reliability_hardening import Model, LONG, SHORT
from apps.api.app.config import get_settings
from apps.api.app.models import NoticeDocument, PreflightCase
from apps.api.app.database import SessionLocal
from apps.api.app.qualification.routers import analysis as routes


@pytest.mark.parametrize('strategy', ['legacy', 'review_v1'])
@pytest.mark.parametrize('scenario', ['wrong_money', 'dedup', 'procedure'])
def test_d1_d3_api_storage_state(dedicated_database_case, monkeypatch, strategy, scenario):
    _, cid, _, _ = dedicated_database_case
    monkeypatch.setattr(get_settings(), 'qualification_review_v1_enabled', True)
    if scenario == 'wrong_money':
        text = '합산 급식 운영 실적은 1일 평균 800식 이상이어야 한다.'
        slots = [{'유형': '실적요건', 'raw': text, '금액_raw': '1일 평균 800식 이상'}]
    elif scenario == 'procedure':
        text = '나라장터 입찰참가자격등록을 마치고 업종코드 1227을 등록한 업체'
        slots = [{'유형': '업종요건', 'raw': text, '업종_raw': '1227'}]
    else:
        text = LONG
        slots = [{'유형': '등록요건', 'raw': SHORT, '등록인증_raw': '단체급식업등록'},
                 {'유형': '업종요건', 'raw': text, '업종_raw': '단체급식업'}]
    model = Model(slots)
    model.available = True
    model.model = 'synthetic-no-network'
    monkeypatch.setattr(routes, 'OpenAIStructuredExtractor', lambda **kw: model)
    with SessionLocal() as db:
        case = db.get(PreflightCase, cid)
        doc = db.scalar(select(NoticeDocument).where(NoticeDocument.notice_version_id == case.current_version_id))
        doc.extracted_blocks = [{'block_index': 0, 'text': text}]
        doc.extracted_text_sha256 = hashlib.sha256(text.encode()).hexdigest()
        db.commit()
        client = make_client(db)
        response = client.post(f'/api/v1/notices/{case.notice_id}/versions/2/qualification-analysis', json={'extraction_strategy': strategy})
        assert response.status_code == 201, response.text
        body = response.json()
        loaded = client.get('/api/v1/qualification-analyses/' + body['id']).json()
        assert loaded == body
        assert loaded['execution_basis']['slot_pipeline_version'] == 'qualification-slot-pipeline-v2'
        if scenario == 'wrong_money':
            assert loaded['status'] == 'PARTIAL' and not loaded['requirements']
            assert any(d['code'] == 'UNMAPPED_PERFORMANCE' and d['details']['detail_field'] == '금액_raw' for d in loaded['diagnostics'])
        elif scenario == 'dedup':
            assert loaded['status'] == 'SUCCEEDED' and len(loaded['requirements']) == 1
            assert loaded['requirements'][0]['value'] == '1450' and len(loaded['requirements'][0]['evidence_keys']) == 2
        else:
            assert loaded['status'] == 'PARTIAL' and loaded['requirements'][0]['value'] == '1227'
            assert any(d['code'] == 'PROCEDURAL_REQUIREMENT_REVIEW' and d['details']['verification_status'] == 'NOT_CHECKED' for d in loaded['diagnostics'])


def test_d4_dropped_detail_survives_post_and_get(dedicated_database_case, monkeypatch):
    _, cid, _, _ = dedicated_database_case
    text = '실적 1억원 이상 보유\n사업 예산 5억원'
    model = Model([{'유형': '실적요건', 'raw': '실적 1억원 이상 보유', '금액_raw': '5억원'}])
    model.available = True
    monkeypatch.setattr(routes, 'OpenAIStructuredExtractor', lambda **kw: model)
    with SessionLocal() as db:
        case = db.get(PreflightCase, cid)
        doc = db.scalar(select(NoticeDocument).where(NoticeDocument.notice_version_id == case.current_version_id))
        doc.extracted_blocks = [{'block_index': 0, 'text': text}]
        doc.extracted_text_sha256 = hashlib.sha256(text.encode()).hexdigest()
        db.commit()
        client = make_client(db)
        response = client.post(f'/api/v1/notices/{case.notice_id}/versions/2/qualification-analysis')
        assert response.status_code == 201, response.text
        body = client.get('/api/v1/qualification-analyses/' + response.json()['id']).json()
        assert not body['requirements']
        assert body['dropped_requirements'][0]['detail_field'] == '금액_raw'
        assert body['dropped_requirements'][0]['detail_value'] == '5억원'
        assert body['dropped_requirements'][0]['validation_code'] == 'QUOTE_NOT_IN_SOURCE'
