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


def test_workspace_migration_requires_exact_receipt_and_container(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, 'ROOT', tmp_path)
    monkeypatch.setattr(evaluation, 'STATE', tmp_path)
    old = str(tmp_path / '.ci-results' / 'evaluation-ready')
    labels = {'copilot.workspace':old}
    assert evaluation.owns_evaluation_workspace({'copilot.workspace':str(tmp_path)}, 'owned-id')
    assert not evaluation.owns_evaluation_workspace(labels, 'owned-id')
    receipt = {'version':1, 'from_workspace':old, 'to_workspace':str(tmp_path),
               'container':evaluation.NAME, 'container_id':'owned-id'}
    path = tmp_path / 'workspace-migration.json'
    path.write_text(json.dumps(receipt))
    assert evaluation.owns_evaluation_workspace(labels, 'owned-id')
    assert not evaluation.owns_evaluation_workspace(labels, 'another-container')
    assert not evaluation.owns_evaluation_workspace({'copilot.workspace':'unrelated'}, 'owned-id')
    for field in receipt:
        path.write_text(json.dumps({**receipt, field:'wrong'}))
        assert not evaluation.owns_evaluation_workspace(labels, 'owned-id'), field
    for malformed in ('[]', '{'):
        path.write_text(malformed)
        assert not evaluation.owns_evaluation_workspace(labels, 'owned-id')


def test_local_controller_reads_allowed_without_external_processing():
    payload = {'intent':'QUALIFICATION_SUMMARY', 'message':'현재 판정 결과'}
    assert evaluation.allowed_evaluation_request(payload)
    assert not evaluation.allowed_evaluation_request(payload, 'true')
    assert not evaluation.allowed_evaluation_request({**payload, 'allow_external_processing':True})
    assert not evaluation.allowed_evaluation_request({**payload, 'public_document_question':'원문'})
    assert not evaluation.allowed_evaluation_request({'message':'임의 대화'})


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


def test_embedding_cannot_bypass_evaluation_budget(budget, monkeypatch):
    monkeypatch.setattr(ModelGateway,'embed_query',lambda *args: [1.0])
    assert orchestration.ModelGateway().embed_query('test') == [1.0]
    ledger=json.loads(budget.read_text())
    assert ledger['reserved_estimate_usd'] > 0 and ledger['calls'][0]['stage']=='query_embedding'
    ledger['cap_estimate_usd']=ledger['reserved_estimate_usd']
    evaluation.save(budget,ledger)
    with pytest.raises(BudgetExceeded):
        orchestration.ModelGateway().embed_query('test')
    assert len(json.loads(budget.read_text())['calls']) == 1


def test_successful_known_usage_settles_once_without_erasing_failed_reservations(tmp_path):
    from scripts.local_model_budget import reserve,finish,settle
    path=tmp_path/'budget.json'
    path.write_text(json.dumps({'cap_estimate_usd':.02,'reserved_estimate_usd':0,'calls':[]}))
    one=reserve(path,'generate',.0068);two=reserve(path,'generate',.0068)
    usage={'prompt_tokens':1000,'completion_tokens':200}
    finish(path,one,status='succeeded',elapsed_ms=1,usage=usage)
    finish(path,two,status='failed',elapsed_ms=1,usage=usage)
    position=settle(path)
    assert position['net_commitment_estimate_usd']==pytest.approx(.0068+.00044)
    assert position['gross_reservations_usd']==pytest.approx(.0136)
    before=path.read_text();settle(path);assert path.read_text()==before
    assert json.loads(path.read_text())['calls'][two]['reserved_estimate_usd']==.0068


def test_unknown_or_invalid_usage_never_releases_budget(tmp_path):
    from scripts.local_model_budget import reserve,finish
    path=tmp_path/'budget.json';path.write_text(json.dumps({'cap_estimate_usd':.01,'reserved_estimate_usd':0,'calls':[]}))
    idx=reserve(path,'generate',.0068)
    finish(path,idx,status='succeeded',elapsed_ms=1,usage={'prompt_tokens':-1,'completion_tokens':0})
    assert json.loads(path.read_text())['reserved_estimate_usd']==.0068
