"""Cross-turn goal preservation and evidence invalidation, without DB/model."""
from uuid import uuid4
from types import SimpleNamespace
import pytest
from apps.api.app.copilot.job_state import bind_plan, finish_turn, reconcile_basis
from apps.api.app.copilot.v31_contracts import ConversationState, Scope, TaskPlan, Task, EvidenceBundle, Fact, Source, Claim


def fixture():
    scope = Scope(case_id=uuid4(), company_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4())
    return ConversationState(conversation_id=uuid4(), owner='test', scope=scope)


def turn(state, question, kind='READ_DOCUMENT', *, partial=False, rid=None, proposed=False):
    plan = TaskPlan(goal=question, tasks=[Task(kind=kind, question=question, requirement_id=rid)])
    bindings = bind_plan(state, plan)
    bundle = EvidenceBundle(scope=state.scope, coverage={kind:'FOUND'}, fingerprints={'document':'v1'},
        facts=[Fact(fact_id='f', kind='NOTICE_FACT', text='본문', source_ids=['s'], scope=state.scope, origin_tool=kind)],
        sources=[Source(source_id='s',kind='DOCUMENT',quote='본문',scope=state.scope)])
    claims = [Claim(claim_id='c',text='확인한 설명입니다.',fact_ids=['f'],source_ids=['s'],validation='SUPPORTED')]
    action = SimpleNamespace(model_dump=lambda **kwargs: {'action': 'test'})
    finish_turn(state,bindings,bundle,claims,[],complete=not partial,turn_id=str(uuid4()),actions=[action] if proposed else [])
    return bindings[0][1]


def test_new_question_does_not_erase_unresolved_goal_and_resume_only_reads():
    state=fixture()
    first=turn(state,'참가요건과 준비할 일을 검토해줘',partial=True)
    turn(state,'제출 마감일은?',partial=False)
    action=turn(state,'입력 반영',kind='PROPOSE_ACTION',proposed=True)
    assert state.job.goal=='참가요건과 준비할 일을 검토해줘'
    assert first.status=='OPEN' and action.status=='AWAITING_CONFIRMATION' and state.job.status=='OPEN'
    plan=TaskPlan(goal='남은 검토를 이어줘',tasks=[Task(kind='READ_DOCUMENT',question='남은 항목',requirement_id=first.requirement_id)],resume_unresolved=True)
    bind_plan(state,plan)
    assert all(t.kind!='PROPOSE_ACTION' for t in plan.tasks)
    assert [t.requirement_id for t in plan.tasks]==[first.requirement_id]


def test_followup_resolves_original_requirement_without_duplicating_or_changing_goal():
    state=fixture();r=turn(state,'참가자격을 검토해줘',partial=True)
    turn(state,'빠진 예외까지 포함해 설명해줘',rid=r.requirement_id)
    assert len(state.job.requirements)==1 and r.request=='참가자격을 검토해줘'
    assert state.job.status=='COMPLETE' and r.last_turn_id and r.source_ids


@pytest.mark.parametrize('change',['version','judgment','document'])
def test_changed_basis_keeps_goal_but_invalidates_answer_receipts(change):
    state=fixture();r=turn(state,'공고 검토')
    scope=state.scope.model_copy(update={'notice_version_id':uuid4()} if change=='version' else {'judgment_run_id':uuid4()} if change=='judgment' else {})
    reconcile_basis(state,scope,{'document':'v2'} if change=='document' else {})
    assert r.status=='STALE' and not r.source_ids and state.job.status=='OPEN'
    assert state.job.goal=='공고 검토'


def test_model_cannot_bind_a_write_to_read_requirement_or_invent_id():
    state=fixture();r=turn(state,'원문 확인')
    for kind,rid in [('PROPOSE_ACTION',r.requirement_id),('READ_DOCUMENT','invented')]:
        with pytest.raises(ValueError):
            bind_plan(state,TaskPlan(goal='다음',tasks=[Task(kind=kind,question='다음',requirement_id=rid)]))


def test_partial_or_unavailable_current_read_does_not_keep_old_complete_status():
    state=fixture();r=turn(state,'조건 설명')
    turn(state,'조건 설명',partial=True,rid=r.requirement_id)
    assert r.status=='OPEN' and state.job.status=='OPEN'


def test_empty_job_and_acknowledgement_cannot_complete_pending_execution():
    state=fixture();r=turn(state,'저장 제안',kind='PROPOSE_ACTION',proposed=True)
    bindings=bind_plan(state,TaskPlan(goal='응',tasks=[Task(kind='ACKNOWLEDGE_ACTION',question='응')]))
    finish_turn(state,bindings,EvidenceBundle(scope=state.scope),[],[],complete=True,turn_id='ack',actions=[])
    assert r.status=='AWAITING_CONFIRMATION' and state.job.status=='OPEN'


def test_execution_receipt_is_owner_case_and_exact_proposal_scoped():
    from apps.api.app.copilot.conversation_state import ConversationRepository
    from apps.api.app.copilot.job_state import apply_execution_receipts
    repository = ConversationRepository()
    state = fixture()
    requirement = turn(state, '저장 요청', kind='PROPOSE_ACTION', proposed=True)
    action = SimpleNamespace(expected=SimpleNamespace(case_id=state.scope.case_id),
                             model_dump=lambda **kwargs: {'action': 'test'})
    result = SimpleNamespace(preflight_case_id=state.scope.case_id, result_judgment_run_id=uuid4())
    assert not repository.execution_receipts(state.owner, state.scope.case_id)
    repository.record_execution(state.owner, action, result)
    assert not repository.execution_receipts('other', state.scope.case_id)
    assert not repository.execution_receipts(state.owner, uuid4())
    apply_execution_receipts(state, repository.execution_receipts(state.owner, state.scope.case_id))
    reconcile_basis(state, state.scope.model_copy(update={'judgment_run_id': result.result_judgment_run_id}))
    assert requirement.status == 'EXECUTED'
    assert requirement.execution_result_ids == [str(result.result_judgment_run_id)]
    assert state.job.status == 'COMPLETE'


def test_execution_receipt_does_not_complete_different_proposal_or_new_read():
    from apps.api.app.copilot.job_state import apply_execution_receipts
    state = fixture()
    pending = turn(state, '저장 요청', kind='PROPOSE_ACTION', proposed=True)
    reading = turn(state, '결과 설명', partial=True)
    apply_execution_receipts(state, {'wrong-key': str(uuid4())})
    assert pending.status == 'AWAITING_CONFIRMATION'
    apply_execution_receipts(state, {pending.action_keys[0]: str(uuid4())})
    reconcile_basis(state, state.scope)
    assert pending.status == 'EXECUTED' and reading.status == 'OPEN' and state.job.status == 'OPEN'
