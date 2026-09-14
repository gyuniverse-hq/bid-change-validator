"""Real Chrome -> HTTP -> authenticated API -> isolated DB -> budgeted model."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from apps.api.tests.test_copilot_v31_db import state, authenticated_api
from apps.api.tests.test_copilot_v31_browser_db import test_browser_login_chat_selected_target_against_real_db as run_browser
from apps.api.app.copilot.model_gateway import ModelGateway, BudgetExceeded


@pytest.fixture
def live_model(monkeypatch):
    if not os.getenv('COPILOT_LIVE_MAX_USD') or not os.getenv('COPILOT_DB_EVIDENCE'):
        pytest.skip('Guarded Docker runner with explicit model budget required')
    from apps.api.app.copilot import orchestration
    output = Path(os.environ['COPILOT_DB_EVIDENCE'])
    cap = float(os.environ['COPILOT_LIVE_MAX_USD'])
    reserved, traces, gateways = [0.0], [], []

    def save():
        calls = [c for g in gateways for c in g.calls]
        cost = sum((c['usage']['prompt_tokens'] * .20 + c['usage']['completion_tokens'] * 1.20) / 1_000_000
                   if c.get('usage') else .0068 for c in calls)
        output.joinpath('model-traces.json').write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding='utf-8')
        output.joinpath('model-usage.json').write_text(json.dumps({'calls': calls, 'usage_upper_usd': cost,
            'reserved_upper_usd': reserved[0], 'cap_usd': cap, 'scope': 'actual model calls; transport scope in browser-results.json or workflow-results.json; synthetic fixture'},
            ensure_ascii=False, indent=2), encoding='utf-8')

    class BudgetedGateway(ModelGateway):
        def call(self, stage, system, body, schema):
            if reserved[0] + .0068 > cap:
                raise BudgetExceeded('EVAL_USD_BUDGET')
            reserved[0] += .0068
            trace = {'stage': stage, 'system': system, 'input': body,
                     'acceptance_sha256': hashlib.sha256(json.dumps(body.get('acceptance'), sort_keys=True).encode()).hexdigest()}
            traces.append(trace)
            try:
                result = super().call(stage, system, body, schema)
                trace['output'] = result.model_dump(mode='json')
                return result
            except Exception as error:
                trace['error_type'] = type(error).__name__
                raise
            finally:
                save()

    def factory():
        gateway = BudgetedGateway(model='gpt-5.6-luna')
        gateways.append(gateway)
        return gateway

    monkeypatch.setattr(orchestration, 'ModelGateway', factory)
    try:
        yield gateways
    finally:
        save()


def test_browser_with_live_model(state, authenticated_api, monkeypatch, live_model):
    monkeypatch.setenv('COPILOT_BROWSER_LIVE', '1')
    run_browser(state, authenticated_api)
    assert any(c['status'] == 'succeeded' for g in live_model for c in g.calls)
