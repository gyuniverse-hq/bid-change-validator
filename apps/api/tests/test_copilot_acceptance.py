"""Frozen task boundaries and fail-closed evidence/coverage controls."""
from uuid import uuid4
import pytest
from apps.api.tests.test_copilot_v31 import bundle, scope, draft, FakeGateway
from apps.api.app.copilot.v31_contracts import ConversationState, Draft, Claim, Task, TaskPlan, Verdicts
from apps.api.app.copilot.acceptance import freeze_acceptance, assess_acceptance
from apps.api.app.copilot.answer_validation import verify, compose


def test_generated_source_edges_come_only_from_selected_server_facts():
    from apps.api.app.copilot.answer_validation import generated_draft, mechanical
    from apps.api.app.copilot.v31_contracts import FactCitedDraft
    b = bundle()
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            return FactCitedDraft(claims=[{'claim_id': 'c', 'text': '회사 보유 사실을 단정하지 않는 설명',
                'fact_ids': [b.facts[0].fact_id], 'speech_act': 'ASSERTION'}])
    result = generated_draft(Gateway(), 'generate', '', {}, b)
    assert result.claims[0].source_ids == b.facts[0].source_ids
    assert mechanical(result.claims[0], b) is None
    # Correct edges do not establish semantic truth; normal verification remains required.
    claims, _ = verify(result, b, FakeGateway({'validate': Verdicts(verdicts=[
        {'claim_id': 'c', 'status': 'CONTRADICTED', 'reason': '실제 문장이 원문과 모순'}])}))
    assert claims[0].validation == 'CONTRADICTED'


def test_compound_goal_cannot_pass_when_selected_reads_omit_requested_document():
    b = bundle()
    p = TaskPlan(goal='저장 판정과 확인할 일, 공고 제출 서류와 마감일을 알려줘', tasks=[
        Task(kind='READ_JUDGMENT', question='저장 판정'), Task(kind='READ_CHECKS', question='확인할 일')])
    criteria = freeze_acceptance(p, b)
    goal = next(c for c in criteria if c.criterion_id == 'GOAL:request')
    assert p.goal in goal.requirement
    rows = [{'criterion_id': c.criterion_id, 'status': 'MET', 'claim_ids': ['c'], 'reason': 'read explained'}
            for c in criteria if c != goal]
    claim = Claim(claim_id='c', text='저장 상태 설명', fact_ids=[f.fact_id for f in b.facts],
                  source_ids=[s.source_id for s in b.sources], validation='SUPPORTED')
    assert assess_acceptance(criteria, Verdicts(verdicts=[], criteria=rows), [claim])['task_coverage'] == 'PARTIAL'
    rows.append({'criterion_id': goal.criterion_id, 'status': 'MISSING', 'claim_ids': [], 'reason': '서류·마감일 누락'})
    assert goal.criterion_id in assess_acceptance(criteria, Verdicts(verdicts=[], criteria=rows), [claim])['missing_criterion_ids']


def test_proposal_completion_requires_server_proposal_evidence():
    from apps.api.app.copilot.orchestration import procedure_fact
    b = bundle()
    p = plan('PROPOSE_ACTION', '등록 항목에 반영해줘')
    empty = freeze_acceptance(p, b)
    assert not empty[0].fact_ids
    fact = procedure_fact(b, 'PROPOSE_ACTION', '등록 보유=True를 저장 전 제안했다. 명시 확인 필요.')
    criteria = freeze_acceptance(p, b)
    claim = Claim(claim_id='proposal', text=fact.text, fact_ids=[fact.fact_id],
                  source_ids=fact.source_ids, validation='SUPPORTED')
    verdict = Verdicts(verdicts=[], criteria=[{'criterion_id': criteria[0].criterion_id,
        'status': 'MET', 'claim_ids': ['proposal'], 'reason': '제안 내용과 저장 전 상태 설명'}])
    assert assess_acceptance(criteria, verdict, [claim])['task_coverage'] == 'COMPLETE'
    assert assess_acceptance(empty, verdict, [claim])['task_coverage'] == 'PARTIAL'
    assert assess_acceptance(criteria, verdict, [claim.model_copy(update={'validation': 'CONTRADICTED'})])['task_coverage'] == 'PARTIAL'


@pytest.mark.parametrize('message', ['응', '네.', '좋아요', '알겠습니다'])
def test_short_acknowledgement_requires_current_server_proposal(message):
    from apps.api.app.copilot.orchestration import plan_turn
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.app.copilot.v31_contracts import Message
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope(), messages=[
        Message(turn_id='previous', question='등록 반영', answer='저장 전 제안', scope=scope(), action_proposed=True)])
    request = CopilotChatRequest(case_id=scope().case_id, message=message)
    gateway = FakeGateway()
    actual, fallback = plan_turn(request, state, gateway)
    assert [t.kind for t in actual.tasks] == ['ACKNOWLEDGE_ACTION'] and not fallback and not gateway.calls
    state.messages[-1].scope = scope().model_copy(update={'judgment_run_id': uuid4()})
    actual, _ = plan_turn(request, state, FakeGateway())
    assert all(t.kind != 'ACKNOWLEDGE_ACTION' for t in actual.tasks)


def test_planner_cannot_invent_acknowledgement_procedure():
    from apps.api.app.copilot.orchestration import plan_turn
    from apps.api.app.copilot.chat import CopilotChatRequest
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    request = CopilotChatRequest(case_id=scope().case_id, message='공고의 등록 조건을 알려줘')
    gateway = FakeGateway({'plan': TaskPlan(goal=request.message, tasks=[Task(kind='ACKNOWLEDGE_ACTION', question='fabricated')])})
    actual, fallback = plan_turn(request, state, gateway)
    assert fallback and all(t.kind != 'ACKNOWLEDGE_ACTION' for t in actual.tasks)


def test_planner_cannot_drop_explicit_hypothetical_boundary():
    from apps.api.app.copilot.orchestration import plan_turn, explicit_assumption
    from apps.api.app.copilot.chat import CopilotChatRequest
    question = '정보통신공사업 등록을 보유하고 있다고 가정하고 해당 조건만 검토해줘.'
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    request = CopilotChatRequest(case_id=scope().case_id, message=question)
    gateway = FakeGateway({'plan': TaskPlan(goal=question, tasks=[Task(kind='READ_JUDGMENT', question=question)])})
    actual, fallback = plan_turn(request, state, gateway)
    assert [t.kind for t in actual.tasks] == ['REVIEW_ASSUMPTION', 'READ_JUDGMENT'] and not fallback
    assert not explicit_assumption('가정하지 말고 현재 저장된 사실만 알려줘')


def test_selected_target_keeps_new_assumption_fact():
    from apps.api.tests.test_copilot_v31 import ReplayTools
    from apps.api.app.copilot.orchestration import coordinate
    from apps.api.app.copilot.conversation_state import ConversationRepository
    from apps.api.app.copilot.chat import CopilotChatRequest
    repo = ConversationRepository()
    first, _ = coordinate(CopilotChatRequest(case_id=scope().case_id, message='원문'), 'u', ReplayTools(),
        repository=repo, gateway=FakeGateway({'plan': plan()}))
    target = first.follow_up_targets[0]
    second, tools = coordinate(CopilotChatRequest(case_id=scope().case_id, message='이 조건을 충족한다고 가정하고 검토해줘',
        target_id=target.target_id, conversation_id=first.conversation_id, context_revision=first.context_revision),
        'u', ReplayTools(), repository=repo, gateway=FakeGateway({'plan': plan('READ_JUDGMENT')}))
    assert second.clarification is None
    assert any(f.kind == 'ASSUMPTION' for f in tools.bundle.facts)
    assert set(target.fact_ids) <= {f.fact_id for f in tools.bundle.facts}
    assert [t['kind'] for t in second.processing.plan['tasks']] == ['READ_DOCUMENT', 'REVIEW_ASSUMPTION']


def test_compound_proof_can_split_premise_and_limitation_but_cannot_omit_basis():
    from apps.api.app.copilot.v31_contracts import AcceptanceCriterion
    criterion = AcceptanceCriterion(criterion_id='assumption', task_kind='REVIEW_ASSUMPTION',
        mode='EXPLANATION', requirement='가정과 조건부 결론 및 한계를 설명한다', fact_ids=('premise',))
    premise = Claim(claim_id='premise-claim', text='등록 보유를 가정합니다.', fact_ids=['premise'], source_ids=['s1'],
        validation='SUPPORTED', speech_act='ASSUMPTION')
    limitation = Claim(claim_id='limitation-claim', text='저장 판정은 UNKNOWN입니다.', fact_ids=['stored-judgment'],
        source_ids=['s2'], validation='SUPPORTED')
    def result(ids):
        return Verdicts(verdicts=[], criteria=[{'criterion_id': 'assumption', 'status': 'MET', 'claim_ids': ids, 'reason': 'fixture'}])
    both = result(['premise-claim', 'limitation-claim'])
    assert assess_acceptance([criterion], both, [premise, limitation])['task_coverage'] == 'COMPLETE'
    assert assess_acceptance([criterion], result(['limitation-claim']), [limitation])['task_coverage'] == 'PARTIAL'
    assert assess_acceptance([criterion], both, [premise, limitation.model_copy(update={'validation': 'CONTRADICTED'})])['task_coverage'] == 'PARTIAL'


def plan(kind='READ_DOCUMENT', question='병원 실적 예외를 알려줘'):
    return TaskPlan(goal=question, tasks=[Task(kind=kind, question=question)])


def test_generate_and_verify_share_frozen_criteria_and_ignore_extra_topics():
    gateway = FakeGateway({'generate': draft(), 'validate': lambda body: {
        'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'fixture'}],
        'task_coverage': 'PARTIAL', 'missing_topics': ['불필요한 추가 증빙'],
        'criteria': [{'criterion_id': c['criterion_id'], 'status': 'MET', 'claim_ids': ['c1'], 'reason': 'answered'}
                     for c in body['acceptance']]}})
    claims, partial, _ = compose(bundle(), plan(), ConversationState(conversation_id=uuid4(), owner='u', scope=scope()), gateway)
    assert not partial and claims
    assert gateway.bodies[0]['acceptance'] == gateway.bodies[1]['acceptance']


def test_check_request_label_cannot_disguise_an_assertion():
    d = draft('회사는 실적 요건을 충족합니다.')
    d.claims[0] = d.claims[0].model_copy(update={'speech_act': 'CHECK_REQUEST'})
    gateway = FakeGateway({'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED',
        'reason': 'bad verifier framing fixture', 'observed_act': 'ASSERTION'}]}})
    claims, _ = verify(d, bundle(), gateway)
    assert claims[0].validation != 'SUPPORTED'


def test_supported_check_is_downgraded_instead_of_published_as_assertion():
    d = draft('실적 증빙은 실제 자료와 대조해 확인하세요.')
    gateway = FakeGateway({'validate': {'verdicts': [{'claim_id':'c1','status':'SUPPORTED',
        'reason':'source-backed check request','observed_act':'CHECK_REQUEST'}]}})
    claims, _ = verify(d, bundle(), gateway)
    assert claims[0].validation == 'SUPPORTED'
    assert claims[0].speech_act == 'CHECK_REQUEST'


@pytest.mark.parametrize('failure', ['extra_id', 'duplicate', 'missing_id', 'bad_claim', 'rejected_claim'])
def test_coverage_cannot_change_rubric_or_use_rejected_claim(failure):
    criteria = freeze_acceptance(plan(), bundle())
    c = Claim(**draft().claims[0].model_dump(), validation='SUPPORTED')
    row = {'criterion_id': criteria[0].criterion_id, 'status': 'MET', 'claim_ids': ['c1'], 'reason': 'fixture'}
    rows = [row]
    if failure == 'extra_id': rows.append({**row, 'criterion_id': 'new-proof-demand'})
    if failure == 'duplicate': rows.append(row)
    if failure == 'missing_id': rows = []
    if failure == 'bad_claim': row['claim_ids'] = ['never-validated']
    if failure == 'rejected_claim': c.validation = 'CONTRADICTED'
    result = Verdicts(verdicts=[], task_coverage='COMPLETE', criteria=rows)
    assert assess_acceptance(criteria, result, [c])['task_coverage'] == 'PARTIAL'


def test_missing_data_cannot_complete_even_with_apology_claim():
    b = bundle(); b.facts = []; b.sources = []
    criteria = freeze_acceptance(plan('READ_PROFILE', '회사정보 요약'), b)
    result = Verdicts(verdicts=[], criteria=[{'criterion_id': c.criterion_id, 'status': 'MET',
        'claim_ids': ['apology'], 'reason': 'explained missing data'} for c in criteria])
    assert assess_acceptance(criteria, result, [])['task_coverage'] == 'PARTIAL'


def test_profile_summary_has_fixed_topics_and_narrow_requests_stay_narrow():
    criteria = freeze_acceptance(plan('READ_PROFILE', '판정에 사용한 회사정보만 요약해줘'), bundle())
    assert [c.criterion_id.split(':')[1] for c in criteria] == ['identity', 'staff', 'performance', 'registration']
    narrow = freeze_acceptance(plan('READ_PROFILE', '회사 인력만 알려줘'), bundle())
    assert [c.criterion_id for c in narrow] == ['READ_PROFILE:staff']
    with pytest.raises(Exception): criteria[0].requirement = '증빙까지 제출'


def test_explicit_profile_scope_cannot_be_expanded_by_planner():
    from apps.api.app.copilot.orchestration import plan_turn
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.app.copilot.acceptance import profile_only_request
    request = CopilotChatRequest(case_id=scope().case_id, message='판정에 사용한 회사정보만 요약해줘.')
    gateway = FakeGateway({'plan': TaskPlan(goal=request.message, tasks=[Task(kind='READ_JUDGMENT', question='판정 추가')])})
    actual, fallback = plan_turn(request, ConversationState(conversation_id=uuid4(), owner='u', scope=scope()), gateway)
    assert [t.kind for t in actual.tasks] == ['READ_PROFILE'] and not fallback and not gateway.calls
    assert not profile_only_request('회사정보만 요약하고 참가 불가 이유도 알려줘')
    assert not profile_only_request('회사정보만 요약해줘. 확인 질문도 알려줘.')
    assert not profile_only_request('등록 조건을 알려주고 회사정보만 요약해줘')
    expanded = actual.model_copy(update={'tasks': [*actual.tasks, Task(kind='READ_JUDGMENT', question='extra')]})
    assert len(freeze_acceptance(expanded, bundle())) == 4


def test_profile_overview_with_example_topic_does_not_drop_other_topics():
    criteria = freeze_acceptance(plan('READ_PROFILE', '실적을 포함해 회사정보 전체를 요약해줘'), bundle())
    assert len(criteria) == 4


def test_missing_topic_repair_cannot_reuse_supported_id():
    good = draft().claims[0].model_copy(update={'claim_id': 'fill-READ_DOCUMENT:request'})
    def repair(body):
        assert good.claim_id not in body['allowed_fill_ids']
        return Draft(claims=[good.model_copy(update={'claim_id': body['allowed_fill_ids'][0], 'text': '병원 급식 실적은 제외됩니다. 추가 조건을 확인했습니다.'})])
    gateway = FakeGateway({'generate': Draft(claims=[good]), 'validate': {
        'verdicts': [{'claim_id': good.claim_id, 'status': 'SUPPORTED', 'reason': 'fixture'}], 'task_coverage': 'PARTIAL'},
        'repair': repair, 'revalidate': lambda body: {'verdicts': [
            {'claim_id': c['claim_id'], 'status': 'SUPPORTED', 'reason': 'fixture'} for c in body['claims']]}})
    claims, partial, events = compose(bundle(), plan(), ConversationState(conversation_id=uuid4(), owner='u', scope=scope()), gateway)
    assert not partial
    assert any(c.claim_id == good.claim_id and c.text == good.text for c in claims)
    assert len({c.claim_id for c in claims}) == len(claims)


def test_repair_echo_cannot_edit_already_supported_sentence():
    good = draft().claims[0].model_copy(update={'claim_id': 'good'})
    bad = draft('병원 실적도 인정됩니다.').claims[0].model_copy(update={'claim_id': 'bad'})
    fixed = bad.model_copy(update={'text': '병원 실적은 제외됩니다.'})
    gateway = FakeGateway({'generate': Draft(claims=[good, bad]), 'validate': {'verdicts': [
        {'claim_id': 'good', 'status': 'SUPPORTED', 'reason': 'fixture'},
        {'claim_id': 'bad', 'status': 'CONTRADICTED', 'reason': 'fixture'}]},
        'repair': Draft(claims=[good.model_copy(update={'text': '이미 통과한 문장 변조'}), fixed]),
        'revalidate': lambda body: {'verdicts': [{'claim_id': c['claim_id'], 'status': 'SUPPORTED', 'reason': 'fixture'}
                                               for c in body['claims']]}})
    claims, partial, events = compose(bundle(), plan(), ConversationState(conversation_id=uuid4(), owner='u', scope=scope()), gateway)
    assert not partial and any(c.claim_id == 'good' and c.text == good.text for c in claims)
    assert not any(c.text == '이미 통과한 문장 변조' for c in claims)
    assert any(e.get('reason') == 'REPAIR_DISCARDED_IDS' for e in events)
