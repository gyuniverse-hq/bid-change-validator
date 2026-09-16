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


def test_structured_declared_answer_uses_fresh_fields_and_rejects_invented_quote(monkeypatch):
    from apps.api.app.copilot.natural_answers import structured_candidate, AnswerMappingClarification
    from apps.api.tests.test_copilot_v31 import FakeGateway
    fields = [{'key':'disposal_permit','label':'처분 허가'}, {'key':'legal_transport_permission','label':'법적 운반 허가'}, {'key':'required_equipment','label':'장비 조건'}]
    q = NS(askable=True, requirement_key='transport', confirmation_basis='current', confirmation_fields=fields)
    checks = NS(provenance='p', questions=[q])
    monkeypatch.setattr('apps.api.app.copilot.natural_answers.product_tools.get_required_checks',lambda *a:checks)
    tools=NS(scope='scope',db=None,case=NS(id='case'),_summary=lambda:NS(provenance='p'))
    state=NS(messages=[NS(scope='scope',turn_id='turn')],targets=[NS(message_id='turn',origin_tool='READ_CHECKS',requirement_key='transport')])
    req=NS(message='처분 허가와 법적 운반 허가는 있어. 장비 조건은 충족하지 못했어. 답변 제안을 만들어줘. 아직 실행하지 마.',user_input=None,target_id=None,requirement_key=None)
    parsed={'factual_answer':True,'fields':[{'key':fields[0]['key'],'value':True,'quote':'처분 허가와 법적 운반 허가는 있어'}, {'key':fields[1]['key'],'value':True,'quote':'처분 허가와 법적 운반 허가는 있어'}, {'key':fields[2]['key'],'value':False,'quote':'장비 조건은 충족하지 못했어'}], 'evidence_held':False}
    gateway=FakeGateway({'parse_answer':parsed})
    key,value=structured_candidate(req,state,tools,gateway)
    assert key=='transport' and value.satisfies_requirement is False and value.evidence_held is False
    assert json.loads(value.normalized_value)['answers']['required_equipment'] is False
    assert [c['stage'] for c in gateway.calls]==['parse_answer']
    state.messages.append(NS(scope='scope',turn_id='hypothetical-followup'))
    assert structured_candidate(req,state,tools,gateway)[0]=='transport'
    parsed['fields'][2]['quote']='모든 장비를 갖추었습니다'
    with pytest.raises(AnswerMappingClarification, match='각각 예/아니요') as issue:
        structured_candidate(req,state,tools,gateway)
    assert issue.value.reason == 'UNCONFIRMED_FIELD_OR_QUOTE'
    req.message='만약 모두 충족한다고 가정하면 답변 제안을 만들어줘'
    before=len(gateway.calls)
    assert structured_candidate(req,state,tools,gateway) is None and len(gateway.calls)==before
    req.message='답변 제안을 만들어줘'
    state.messages[-1].scope='different'
    assert structured_candidate(req,state,tools,gateway) is None


def test_assumption_is_not_planned_as_answer_proposal():
    from apps.api.app.copilot.orchestration import plan_turn
    from apps.api.tests.test_copilot_v31 import FakeGateway,scope
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.app.copilot.v31_contracts import ConversationState
    from uuid import uuid4
    state=ConversationState(conversation_id=uuid4(),owner='owner',scope=scope())
    req=CopilotChatRequest(case_id=state.scope.case_id,message='법적 허가와 장비 조건을 충족한다고 가정하면 어떻게 돼? 저장은 하지 마.')
    gateway=FakeGateway({'plan':{'goal':req.message,'tasks':[{'kind':'READ_JUDGMENT','question':req.message},{'kind':'PROPOSE_ACTION','question':req.message}]}})
    plan,_=plan_turn(req,state,gateway)
    assert 'REVIEW_ASSUMPTION' in [t.kind for t in plan.tasks]
    assert 'PROPOSE_ACTION' not in [t.kind for t in plan.tasks]


def test_unmapped_explicit_answer_asks_clarification_without_read_fallback(monkeypatch):
    from apps.api.app.copilot.natural_answers import AnswerMappingClarification
    from apps.api.tests.test_copilot_v31 import ReplayTools, FakeGateway
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.app.copilot.orchestration import coordinate
    from apps.api.app.copilot.conversation_state import ConversationRepository
    def cannot_map(*args):
        raise AnswerMappingClarification([{'key':'permit','label':'법적 허가'}], 'UNCONFIRMED_FIELD_OR_QUOTE')
    monkeypatch.setattr('apps.api.app.copilot.natural_answers.structured_candidate', cannot_map)
    tools, gateway = ReplayTools(), FakeGateway()
    result, _ = coordinate(CopilotChatRequest(case_id=tools.scope.case_id,
        message='허가가 있어. 이 답변으로 제안을 만들어줘. 아직 실행하지 마.'),
        'owner', tools, repository=ConversationRepository(), gateway=gateway)
    assert '법적 허가' in result.clarification and '저장이나 재판정은 하지 않았습니다' in result.clarification
    assert not result.actions and result.processing.task_status != 'PASS'
    assert not result.claims and not gateway.calls
