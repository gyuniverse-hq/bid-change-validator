"""Explicit opt-in only via test_copilot_db.py --live-model. Synthetic persisted data."""
import json
import os
from pathlib import Path

import pytest

from apps.api.tests.test_copilot_v31_db import state, authenticated_api
from apps.api.app.copilot.model_gateway import ModelGateway, BudgetExceeded


def test_real_login_db_model_dialogue(state, authenticated_api, monkeypatch):
    if not os.getenv('COPILOT_LIVE_MAX_USD'):
        pytest.skip('Explicit budgeted live-model runner required')
    from apps.api.app.copilot import orchestration
    # Reserve the maximum bounded call cost BEFORE each request. Usage-free
    # failures keep their reservation; retries cannot exceed the caller's budget.
    reserved, calls, rows = [0.0], [], []
    cap = float(os.environ['COPILOT_LIVE_MAX_USD'])
    class BudgetedGateway(ModelGateway):
        def call(self, *args, **kwargs):
            upper = (16000 * 0.20 + 3000 * 1.20) / 1_000_000
            if reserved[0] + upper > cap:
                raise BudgetExceeded('EVAL_USD_BUDGET')
            reserved[0] += upper
            try:
                return super().call(*args, **kwargs)
            finally:
                calls[:] = [c for g in gateways for c in g.calls]
    gateways = []
    def factory():
        g = BudgetedGateway(model='gpt-5.6-luna')
        gateways.append(g)
        return g
    monkeypatch.setattr(orchestration, 'ModelGateway', factory)
    _, case, _, _ = state
    envelope = None
    try:
        for question in ['현재 추가 답변이 필요한 확인 질문을 알려줘.', '판정에 사용한 회사정보만 요약해줘.']:
            response = authenticated_api.post('/api/v1/copilot/chat',
                headers={'X-Copilot-Semantic-Processing': 'true'}, json={
                    'case_id': str(case.id), 'message': question, 'response_version': '3.1',
                    'conversation_id': envelope['conversation_id'] if envelope else None,
                    'context_revision': envelope['context_revision'] if envelope else None})
            assert response.status_code == 200
            envelope = response.json()['envelope']
            rows.append({'question': question, 'envelope': envelope})
            assert envelope['claims'] and not envelope['clarification']
            assert any(c['method'] == 'semantic' for c in envelope['claims'])
            assert envelope['processing']['task_status'] == 'PASS'
            assert not envelope['actions']
    finally:
        cost = sum((c['usage']['prompt_tokens'] * 0.20 + c['usage']['completion_tokens'] * 1.20) / 1_000_000
                   if c.get('usage') else 0.0068 for c in calls)
        Path(os.environ['COPILOT_DB_EVIDENCE'], 'live-results.json').write_text(json.dumps({
            'scope': 'real login/session + HTTP ASGI + PostgreSQL + product adapters + model; synthetic data',
            'rows': rows, 'calls': calls, 'reserved_upper_usd': reserved[0], 'usage_upper_usd': cost},
            ensure_ascii=False, indent=2), encoding='utf-8')
