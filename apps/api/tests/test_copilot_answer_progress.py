"""Partial completion never trusts stale evidence or unvalidated citations."""
from uuid import uuid4
import pytest
from apps.api.app.copilot.v31_contracts import (ConversationState, Scope, Fact, Source,
    EvidenceBundle, Task, TaskPlan, Draft, Verdicts)
from apps.api.app.copilot.answer_validation import _compose_basic
from apps.api.app.copilot.job_state import bind_plan, finish_turn


def setup():
    scope = Scope(case_id=uuid4(), company_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4())
    state = ConversationState(conversation_id=uuid4(), owner='owner', scope=scope)
    bundle = EvidenceBundle(scope=scope, coverage={'READ_JUDGMENT': 'FOUND', 'READ_DOCUMENT': 'FOUND'})
    for fid, kind, text in [('judgment', 'READ_JUDGMENT', '저장 판정 미달 1건'),
                            ('document', 'READ_DOCUMENT', '제안서는 7월 27일 15시까지 방문 제출')]:
        bundle.facts.append(Fact(fact_id=fid, kind='SERVER_RESULT' if fid == 'judgment' else 'NOTICE_FACT',
            text=text, origin_tool=kind, source_ids=[fid], scope=scope))
        bundle.sources.append(Source(source_id=fid, kind='PRODUCT' if fid == 'judgment' else 'DOCUMENT', quote=text, scope=scope))
    plan = TaskPlan(goal='저장 판정과 제출 절차를 알려줘', tasks=[
        Task(kind='READ_JUDGMENT', question='저장 판정'), Task(kind='READ_DOCUMENT', question='제출 절차')])
    return state, bundle, plan


class Gateway:
    large_context = True
    def __init__(self, second=False): self.calls, self.second = [], second
    def remaining(self): return 120
    def call(self, stage, prompt, body, schema):
        self.calls.append((stage, body))
        if stage == 'generate':
            fid = 'document' if self.second else 'judgment'
            if self.second:
                assert body['supported_siblings'] and len(body['acceptance']) == 2
            return Draft(claims=[dict(claim_id='c', text='제안서는 7월 27일 15시까지 방문 제출합니다.' if self.second else '저장 판정은 미달 1건입니다.',
                                     fact_ids=[fid], source_ids=[fid])])
        assert stage == 'validate'
        claims = body['claims']
        all_ids = [c['claim_id'] for c in claims + body['supported_siblings']]
        return Verdicts(verdicts=[dict(claim_id=c['claim_id'], status='SUPPORTED', reason='source supports text') for c in claims],
            criteria=[dict(criterion_id=c['criterion_id'], status='MET' if self.second or c['task_kind']=='READ_JUDGMENT' else 'MISSING',
                           claim_ids=all_ids if self.second else [claims[0]['claim_id']] if c['task_kind']=='READ_JUDGMENT' else [],
                           reason='제출 단계 설명 필요') for c in body['acceptance']])


def test_partial_progress_resumes_only_missing_explanations_and_has_no_hidden_repair():
    state, bundle, plan = setup()
    bindings = bind_plan(state, plan)
    first = Gateway()
    claims, partial, events = _compose_basic(bundle, plan, state, first)
    assert partial and len(first.calls) == 2
    finish_turn(state, bindings, bundle, claims, events, complete=False, turn_id='first', actions=[])
    assert [r.status for r in state.job.requirements] == ['ANSWERED', 'OPEN']
    assert state.job.requirements[1].remaining == ['제출 절차']
    plan.resume_unresolved = True
    second = Gateway(second=True)
    claims, partial, events = _compose_basic(bundle, plan, state, second)
    assert not partial and len(second.calls) == 2
    assert len([c for c in claims if '저장 판정' in c.text]) == 1
    assert any(e['stage'] == 'answer_resume' for e in events)
    third = Gateway(second=True)
    _, partial, _ = _compose_basic(bundle, plan, state, third)
    assert not partial and not third.calls


@pytest.mark.parametrize('change', ['source', 'profile', 'scope', 'goal', 'coverage'])
def test_current_basis_change_prevents_any_prose_reuse(change):
    state, bundle, plan = setup()
    _compose_basic(bundle, plan, state, Gateway())
    plan.resume_unresolved = True
    if change == 'source': bundle.sources[-1].quote = '마감은 16시로 변경'
    elif change == 'profile': bundle.fingerprints['product'] = 'changed-profile'
    elif change == 'scope': bundle.scope = bundle.scope.model_copy(update={'company_id':uuid4()})
    elif change == 'goal': plan.goal = '다른 요청'
    else: bundle.coverage['READ_DOCUMENT'] = 'UNAVAILABLE'
    gateway = Gateway()
    _compose_basic(bundle, plan, state, gateway)
    assert not gateway.calls[0][1]['supported_siblings']


def test_claim_reference_without_validated_criterion_never_completes_task():
    state, bundle, plan = setup()
    bindings = bind_plan(state, plan)
    claims, _, events = _compose_basic(bundle, plan, state, Gateway())
    assessment = next(e for e in events if 'task_coverage' in e)
    assessment['reason'] = 'CRITERION_SET_MISMATCH'
    finish_turn(state, bindings, bundle, claims, events, complete=False, turn_id='first', actions=[])
    assert all(r.status == 'OPEN' for r in state.job.requirements)


def test_completed_job_cannot_replace_new_followup_with_old_cached_reads():
    state, bundle, original = setup()
    bind_plan(state, original)
    state.job.status = 'COMPLETE'
    for r in state.job.requirements:r.status = 'ANSWERED'
    state.answer_review = {'key': 'previous'}
    plan = TaskPlan(goal='판정 변화와 아직 확인할 사항', resume_unresolved=True, tasks=[
        Task(kind='READ_JUDGMENT', question='전후 판정을 설명'),
        Task(kind='READ_CHECKS', question='아직 확인할 사항')])
    bind_plan(state, plan)
    assert not plan.resume_unresolved
    assert [t.kind for t in plan.tasks] == ['READ_JUDGMENT', 'READ_CHECKS']
    assert plan.tasks[1].question == '아직 확인할 사항'


def test_partial_resume_keeps_new_read_alongside_pending_work():
    state, bundle, original = setup()
    bind_plan(state, original)
    state.answer_review = {'key': 'previous'}
    plan = TaskPlan(goal='이어서 보고 추가 확인사항도 알려줘', resume_unresolved=True,
                    tasks=[Task(kind='READ_CHECKS',question='새로 요청한 확인사항')])
    bind_plan(state, plan)
    assert plan.tasks[0].kind=='READ_CHECKS' and plan.tasks[0].question=='새로 요청한 확인사항'
    assert [t.kind for t in plan.tasks] == ['READ_CHECKS']
    assert {'READ_JUDGMENT','READ_DOCUMENT'} <= {r.tool for r in state.job.requirements}


def test_resume_preserves_new_deliverable_even_with_same_tool_and_requirement():
    state, bundle, original = setup()
    bind_plan(state, original)
    state.answer_review = {'key': 'previous'}
    rid = state.job.requirements[1].requirement_id
    plan = TaskPlan(goal='지난 일정을 구분한 체크리스트를 만들어줘', resume_unresolved=True,
                    tasks=[Task(kind='READ_DOCUMENT', question='필수와 협조사항을 구분한 실행 체크리스트', requirement_id=rid)])
    bind_plan(state, plan)
    assert plan.goal == '지난 일정을 구분한 체크리스트를 만들어줘'
    assert plan.tasks[0].question == '필수와 협조사항을 구분한 실행 체크리스트'
    assert plan.tasks[0].requirement_id == rid


def test_generation_budget_failure_is_not_reported_as_missing_source():
    from apps.api.app.copilot.model_gateway import BudgetExceeded
    class Limited(Gateway):
        def call(self, *args, **kwargs):
            raise BudgetExceeded('LOCAL_EVALUATION_BUDGET_EXHAUSTED')
    state, bundle, plan = setup()
    claims, partial, events = _compose_basic(bundle, plan, state, Limited())
    assert partial
    assert any('모델 처리 한도' in text for text in bundle.limitations)
    assert any(e.get('reason') == 'LOCAL_EVALUATION_BUDGET_EXHAUSTED' for e in events)


def test_validation_budget_failure_is_visible_without_accepting_unverified_prose():
    from apps.api.app.copilot.model_gateway import BudgetExceeded
    class Limited(Gateway):
        def call(self, stage, *args, **kwargs):
            if stage == 'validate':
                raise BudgetExceeded('LOCAL_EVALUATION_BUDGET_EXHAUSTED')
            return super().call(stage, *args, **kwargs)
    state, bundle, plan = setup()
    claims, partial, events = _compose_basic(bundle, plan, state, Limited())
    assert partial
    assert any('설명 검증을 완료하지 못했습니다' in text for text in bundle.limitations)
    assert not any(c.method == 'semantic' for c in claims)
