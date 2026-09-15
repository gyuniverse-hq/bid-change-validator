from types import SimpleNamespace as NS
import json
import pytest
from apps.api.app.copilot.natural_answers import visit_values, visit_candidate


@pytest.mark.parametrize('message', [
    '만약 현장 방문은 완료했지만 확인서는 아직 제출하지 않았어',
    '현장 방문은 완료했지만 확인서는 아직 제출하지 않았어?',
    '현장 방문은 완료했어',
    '현장 방문은 완료했지만 확인서는 아직 제출하지 않았어. 저장하지 마',
    '다른 회사는 현장 방문은 완료했지만 확인서는 아직 제출하지 않았어',
])
def test_non_explicit_or_compound_answers_are_not_inferred(message):
    assert visit_values(message) is None


def test_split_visit_answer_uses_current_basis_without_evidence_inference(monkeypatch):
    q = NS(askable=True, requirement_key='visit', confirmation_basis='current-hash',
           confirmation_fields=[{'key':'site_visited'}, {'key':'visit_certificate'}])
    checks = NS(provenance='current', questions=[q])
    monkeypatch.setattr('apps.api.app.copilot.natural_answers.product_tools.get_required_checks', lambda *a: checks)
    tools = NS(scope='scope', db=None, case=NS(id='case'), _summary=lambda:NS(provenance='current'))
    state = NS(messages=[NS(scope='scope', turn_id='latest')],
               targets=[NS(message_id='latest', origin_tool='READ_CHECKS', requirement_key='visit')])
    req = NS(message='현장 방문은 완료했지만 확인서는 아직 제출하지 않았어',
             user_input=None, target_id=None, requirement_key=None)
    key, value = visit_candidate(req, state, tools)
    assert key == 'visit' and value.satisfies_requirement is False and value.evidence_held is False
    assert json.loads(value.normalized_value) == {'basis':'current-hash', 'answers':{'site_visited':True,'visit_certificate':False}}
    q.askable = False
    assert visit_candidate(req, state, tools) is None
    q.askable = True
    state.targets[0].message_id = 'older'
    assert visit_candidate(req, state, tools) is None
    state.targets[0].message_id = 'latest'
    state.messages[0].scope = 'other-company'
    assert visit_candidate(req, state, tools) is None


def test_server_proposal_confirmation_does_not_call_explanation_model(monkeypatch):
    from apps.api.tests.test_copilot_v31 import ReplayTools, FakeGateway
    from apps.api.app.copilot.contracts import ActionInput, AnswerProposal, ProductProvenance
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.app.copilot.orchestration import coordinate
    from apps.api.app.copilot.conversation_state import ConversationRepository
    tools = ReplayTools()
    tools.db, tools.case = None, NS(id=tools.scope.case_id)
    value = ActionInput(satisfies_requirement=False, normalized_value=json.dumps(
        {'basis':'hash', 'answers':{'site_visited':True,'visit_certificate':False}}))
    monkeypatch.setattr('apps.api.app.copilot.natural_answers.visit_candidate', lambda *a: ('visit',value))
    expected = ProductProvenance(**tools.scope.model_dump(), version_number=2, analysis_status='PARTIAL', rule_version='test')
    proposal = AnswerProposal(expected=expected, requirement_key='visit', user_input=value)
    monkeypatch.setattr('apps.api.app.copilot.actions.propose_answer', lambda *a:proposal)
    gateway = FakeGateway()
    result, _ = coordinate(CopilotChatRequest(case_id=tools.case.id, message='현장 방문은 완료했지만 확인서는 아직 제출하지 않았어'),
        'owner', tools, repository=ConversationRepository(), gateway=gateway)
    assert result.actions == [proposal] and result.processing.task_status == 'PASS'
    answer = '\n'.join(c.text for c in result.claims)
    assert '확인서 미제출' in answer and '아직 저장하지 않았습니다' in answer
    assert gateway.calls == []


def test_preview_suffix_is_proposal_only_and_rejects_extra_execution():
    text = '현장 방문은 완료했지만 확인서는 아직 제출하지 않았어. 이 답변을 반영하면 무엇이 바뀌는지 먼저 보여줘. 아직 저장하지 마.'
    assert visit_values(text) == {'site_visited': True, 'visit_certificate': False}
    assert visit_values(text + ' 지금 실행해.') is None
