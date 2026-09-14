"""Persistent evaluation budget must not reset or race across model calls."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest

from scripts import local_copilot_evaluation as evaluation
from apps.api.app.copilot import orchestration
from apps.api.app.copilot.model_gateway import ModelGateway, BudgetExceeded


@pytest.fixture
def budget(tmp_path, monkeypatch):
    import openai
    monkeypatch.setattr(evaluation, 'STATE', tmp_path)
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: object())
    monkeypatch.setattr(orchestration, 'ModelGateway', ModelGateway)
    monkeypatch.setattr(ModelGateway, 'call', lambda *args, **kwargs: 'result')
    path = tmp_path / 'model-budget.json'
    evaluation.save(path, {'cap_estimate_usd':.0136,'reserved_estimate_usd':0,'calls':[]})
    evaluation.install_budgeted_model('synthetic-test-key')
    return path


def call(gateway):
    return gateway.call('generate', 'test', {}, None)


def test_recreating_gateway_and_server_adapter_does_not_reset_budget(budget):
    assert call(orchestration.ModelGateway()) == 'result'
    evaluation.install_budgeted_model('synthetic-test-key')
    assert call(orchestration.ModelGateway()) == 'result'
    with pytest.raises(BudgetExceeded):
        call(orchestration.ModelGateway())
    ledger = json.loads(budget.read_text())
    assert ledger['reserved_estimate_usd'] == .0136 and len(ledger['calls']) == 2


def test_failed_calls_keep_their_reservation(budget, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('provider failure')
    monkeypatch.setattr(ModelGateway, 'call', fail)
    with pytest.raises(RuntimeError):
        call(orchestration.ModelGateway())
    ledger = json.loads(budget.read_text())
    assert ledger['reserved_estimate_usd'] == .0068 and ledger['calls'][0]['status'] == 'failed'


def test_parallel_document_calls_cannot_overspend(budget):
    def attempt(_):
        try:
            call(orchestration.ModelGateway())
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert sum(outcomes) == 2
    assert len(json.loads(budget.read_text())['calls']) == 2


def test_embedding_cannot_bypass_evaluation_budget(budget):
    with pytest.raises(BudgetExceeded):
        orchestration.ModelGateway().embed_query('test')
    assert json.loads(budget.read_text())['reserved_estimate_usd'] == 0
