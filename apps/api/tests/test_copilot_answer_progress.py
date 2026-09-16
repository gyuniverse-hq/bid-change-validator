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


def test_evidence_flag_is_not_a_rule_comparison_operand_or_failure_cause():
    from types import SimpleNamespace
    from apps.api.app.copilot.tool_adapters import ProductTools
    from apps.api.app.copilot.answer_validation import mechanical
    from apps.api.app.copilot.v31_contracts import CandidateClaim
    item=SimpleNamespace(type='INDUSTRY',raw='급식업 등록',status='UNSATISFIED',basis_type='PROFILE',
        value_source='stored_profile',evidence_status='none',unknown_reason=None,
        evaluated_condition={'operator':'MATCH','value':'급식업','source_contract':None})
    snapshot={'industries':[{'name':'1450','code':'1450','verified':False}]}
    basis=ProductTools._judgment_basis(item,snapshot)
    assert basis['stored_profile_inputs']['industries'] == [{'name':'1450','code':'1450'}]
    assert basis['verification_flags_affect_status'] is False
    assert snapshot['industries'][0]['verified'] is False  # original snapshot preserved
    item.type='EXPERIENCE_FIELD'
    assert '문자열 대조' in ProductTools._judgment_basis(item,snapshot)['comparison_semantics']
    _,bundle,_=setup();bundle.server_context['judgment_basis']=[basis]
    claim=CandidateClaim(claim_id='c',text='업종코드는 1450이지만 검증되지 않아 현재 미달입니다.',
        fact_ids=['judgment'],source_ids=['judgment'])
    assert mechanical(claim,bundle)=='VERIFICATION_FLAG_AS_JUDGMENT_CAUSE'
    claim.text='저장 업종 비교값이 일치하지 않아 미달입니다. 증빙 검증과는 별개입니다.'
    assert mechanical(claim,bundle) is None
    claim.text='미검증이므로 미달이라는 뜻은 아닙니다.'
    assert mechanical(claim,bundle) is None


def test_consolidated_checklist_keeps_same_document_at_two_current_stages():
    from apps.api.app.copilot.answer_progress import save_review, submission_artifact
    from apps.api.app.copilot.v31_contracts import Claim
    from apps.api.app.copilot.submission_obligations import SubmissionObligation
    state,bundle,plan=setup()
    claims=[]
    for i,stage in enumerate(['입찰참가등록','계약체결']):
        row=SubmissionObligation(document='안전보건 이행서약서',stage=stage,stage_kind=stage,
            obligation='필수',deadline='해당 단계 시',method='제출',timing='시점 미확정',conditions='각 단계별로 제출')
        claims.append(Claim(claim_id=str(i),text=stage+' 서약서 제출',fact_ids=['document'],source_ids=['document'],
            validation='SUPPORTED',method='semantic',submission=row))
    save_review(state,'previous',claims,None,bundle=bundle)
    plan.goal='지금까지 내용을 모아 실행 체크리스트를 만들어줘'
    plan.resume_unresolved=False
    assert len(submission_artifact(state,bundle,plan))==2
    plan.goal='남은 것만 체크리스트로 알려줘'
    assert submission_artifact(state,bundle,plan)==[]
    plan.goal='전체 체크리스트를 만들어줘'
    bundle.sources[1].quote='원문이 바뀌었습니다'
    assert submission_artifact(state,bundle,plan)==[]


def test_checklist_preserves_verified_attendance_prose_but_not_stale_proof():
    from apps.api.app.copilot.answer_progress import save_review, submission_artifact
    from apps.api.app.copilot.v31_contracts import Claim
    state,bundle,plan=setup()
    text='설명회는 7월 20일 14시이며 사업자등록증 사본과 위임장 또는 재직증명서, 신분증을 제출합니다.'
    bundle.sources[1].quote=text
    claim=Claim(claim_id='attendance',text=text,fact_ids=['document'],source_ids=['document'],
        validation='SUPPORTED',method='semantic')
    save_review(state,'prior',[claim],None,bundle=bundle)
    plan.goal='전체 준비 체크리스트를 만들어줘'
    assert [c.text for c in submission_artifact(state,bundle,plan)] == [text]
    bundle.sources[1].quote='변경된 일정과 참석서류'
    assert submission_artifact(state,bundle,plan)==[]


@pytest.mark.parametrize('has_retained_prose', [False, True])
def test_retained_submission_does_not_auto_complete_a_new_goal(monkeypatch, has_retained_prose):
    from apps.api.app.copilot.answer_progress import save_review
    from apps.api.app.copilot.v31_contracts import Claim
    from apps.api.app.copilot.submission_obligations import SubmissionObligation
    state,bundle,plan=setup()
    row=SubmissionObligation(document='서약서',stage='계약체결',stage_kind='계약체결',obligation='필수',
        deadline='계약 시',method='제출',timing='시점 미확정',conditions='선정 후 제출')
    save_review(state,'previous',[Claim(claim_id='old',text='서약서 제출',fact_ids=['document'],source_ids=['document'],
        validation='SUPPORTED',method='semantic',submission=row)],None,bundle=bundle)
    plan.goal='지금까지 바탕으로 회사 상태와 전체 체크리스트를 만들어줘'
    if has_retained_prose:
        existing = Claim(claim_id='reviewed-0',text='저장 판정 미달 1건',fact_ids=['judgment'],source_ids=['judgment'],
                         validation='SUPPORTED',method='semantic')
        monkeypatch.setattr('apps.api.app.copilot.answer_progress.resume_review', lambda *a, **k: ([existing], None))
    class G:
        large_context=True
        def remaining(self):return 0
        def call(self,stage,prompt,body,schema):
            if stage=='generate':
                assert len(body['supported_siblings'])==1+int(has_retained_prose)
                return Draft(claims=[dict(claim_id='new',text='추가 확인 필요',fact_ids=['judgment'],source_ids=['judgment'])])
            return Verdicts(verdicts=[dict(claim_id='new-0-new',status='SUPPORTED',reason='current')],
                criteria=[dict(criterion_id=c['criterion_id'],status='MISSING',claim_ids=[],reason='전체 설명 미완료') for c in body['acceptance']])
    claims,partial,events=_compose_basic(bundle,plan,state,G())
    assert partial
    assert any(c.submission is not None for c in claims)
    assert any(e['stage']=='submission_artifact' for e in events)
    from apps.api.app.copilot.answer_progress import visible_claims
    delivered, _ = visible_claims(claims, events)
    assert any(c.submission is not None for c in delivered)
    assert not any(c.claim_id == 'reviewed-0' for c in delivered)


def test_partial_progress_resumes_only_missing_explanations_and_has_no_hidden_repair():
    state, bundle, plan = setup()
    bindings = bind_plan(state, plan)
    first = Gateway()
    claims, partial, events = _compose_basic(bundle, plan, state, first)
    assert partial and len(first.calls) == 2
    finish_turn(state, bindings, bundle, claims, events, complete=False, turn_id='first', actions=[])
    assert {r.tool: r.status for r in state.job.requirements} == {'GOAL': 'OPEN', 'READ_JUDGMENT': 'ANSWERED', 'READ_DOCUMENT': 'OPEN'}
    assert next(r for r in state.job.requirements if r.tool == 'READ_DOCUMENT').remaining == ['제출 절차']
    plan.resume_unresolved = True
    second = Gateway(second=True)
    claims, partial, events = _compose_basic(bundle, plan, state, second)
    assert not partial and len(second.calls) == 2
    assert len([c for c in claims if '저장 판정' in c.text]) == 1
    assert any(e['stage'] == 'answer_resume' for e in events)
    third = Gateway(second=True)
    _, partial, _ = _compose_basic(bundle, plan, state, third)
    assert not partial and not third.calls


@pytest.mark.parametrize('change', ['source', 'profile', 'scope', 'coverage'])
def test_current_basis_change_prevents_any_prose_reuse(change):
    state, bundle, plan = setup()
    _compose_basic(bundle, plan, state, Gateway())
    plan.resume_unresolved = True
    if change == 'source': bundle.sources[-1].quote = '마감은 16시로 변경'
    elif change == 'profile': bundle.fingerprints['product'] = 'changed-profile'
    elif change == 'scope': bundle.scope = bundle.scope.model_copy(update={'company_id':uuid4()})
    else: bundle.coverage['READ_DOCUMENT'] = 'UNAVAILABLE'
    gateway = Gateway()
    _compose_basic(bundle, plan, state, gateway)
    assert not gateway.calls[0][1]['supported_siblings']


def test_new_goal_reuses_supported_prose_but_must_validate_its_own_completion():
    state, bundle, plan = setup()
    _compose_basic(bundle, plan, state, Gateway())
    plan.resume_unresolved = True
    plan.goal = '앞선 내용을 바탕으로 제출 순서를 정리해줘'
    gateway = Gateway()
    _, partial, _ = _compose_basic(bundle, plan, state, gateway)
    assert gateway.calls[0][1]['supported_siblings']
    assert partial
    assert any(c['task_kind'] == 'GOAL' and plan.goal in c['requirement'] for c in gateway.calls[0][1]['acceptance'])


def test_rejected_reason_survives_followup_only_while_its_source_matches():
    from apps.api.app.copilot.answer_progress import save_review,current_review_context
    from apps.api.app.copilot.v31_contracts import CandidateClaim
    state,bundle,plan=setup()
    rejected=CandidateClaim(claim_id='wrong',text='16시에 제출한다',fact_ids=['document'],source_ids=['document'],
        validation='CONTRADICTED',reason='원문은 15시')
    save_review(state,'first',[],None,bundle=bundle,rejected=[rejected])
    assert current_review_context(state,bundle)[1][0]['reason']=='원문은 15시'
    bundle.sources[-1].quote='현재 17시로 변경'
    assert not current_review_context(state,bundle)[1]


def test_new_passage_does_not_erase_fresh_verified_check_receipt():
    from apps.api.app.copilot.answer_progress import resume_review,review_key
    from apps.api.app.copilot.acceptance import freeze_acceptance
    state,bundle,plan=setup()
    _compose_basic(bundle,plan,state,Gateway())
    plan.resume_unresolved=True
    bundle.facts.append(Fact(fact_id='new',kind='NOTICE_FACT',text='새 제출 방법',
        origin_tool='READ_DOCUMENT',source_ids=['new'],scope=bundle.scope))
    bundle.sources.append(Source(source_id='new',kind='DOCUMENT',quote='새 제출 방법',scope=bundle.scope))
    criteria=freeze_acceptance(plan,bundle)
    retained,assessment=resume_review(state,review_key(bundle,plan,criteria),plan,bundle=bundle,criteria=criteria)
    assert retained and retained[0].fact_ids==['judgment']
    assert any(r['status']=='MISSING' for r in assessment['criteria'])
    bundle.sources[0].quote='저장 판정 변경'
    retained,_=resume_review(state,'changed',plan,bundle=bundle,criteria=criteria)
    assert not retained


def test_checks_only_turn_preserves_previous_verified_document_context():
    from apps.api.app.copilot.answer_progress import save_review,current_review_context
    from apps.api.app.copilot.v31_contracts import Claim
    state,bundle,_=setup()
    claim=Claim(claim_id='doc',text='발표자는 제안사 또는 제조사의 임직원',fact_ids=['document'],
                source_ids=['document'],validation='SUPPORTED',method='semantic')
    save_review(state,'first',[claim],None,bundle=bundle)
    middle=bundle.model_copy(deep=True);middle.facts=middle.facts[:1];middle.sources=middle.sources[:1]
    save_review(state,'middle',[],None,bundle=middle)
    assert not current_review_context(state,middle)[0]
    assert current_review_context(state,bundle)[0][0]['text']==claim.text
    bundle.sources[-1].quote='변경된 원문'
    assert not current_review_context(state,bundle)[0]


def test_resume_can_reference_an_earlier_turn_without_blindly_completing_new_goal():
    from apps.api.app.copilot.answer_progress import save_review,resume_review,review_key
    from apps.api.app.copilot.acceptance import freeze_acceptance
    from apps.api.app.copilot.v31_contracts import Claim
    state,bundle,plan=setup()
    first=Claim(claim_id='first',text='먼저 확인한 변경',fact_ids=['document'],source_ids=['document'],
                validation='SUPPORTED',method='semantic')
    save_review(state,'first',[first],None,bundle=bundle)
    middle=bundle.model_copy(deep=True);middle.facts=middle.facts[:1];middle.sources=middle.sources[:1]
    save_review(state,'middle',[],None,bundle=middle)
    plan.resume_unresolved=True;criteria=freeze_acceptance(plan,bundle)
    retained,assessment=resume_review(state,review_key(bundle,plan,criteria),plan,bundle=bundle,criteria=criteria)
    assert len(retained)==1 and retained[0].text==first.text
    assert assessment['task_coverage']=='PARTIAL' and assessment['missing_criterion_ids']


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
    assert [t.kind for t in plan.tasks] == ['READ_CHECKS', 'READ_JUDGMENT', 'READ_DOCUMENT']
    assert {'READ_JUDGMENT','READ_DOCUMENT'} <= {r.tool for r in state.job.requirements}


def test_resume_preserves_new_deliverable_even_with_same_tool_and_requirement():
    state, bundle, original = setup()
    bind_plan(state, original)
    state.answer_review = {'key': 'previous'}
    rid = next(r.requirement_id for r in state.job.requirements if r.tool == 'READ_DOCUMENT')
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


@pytest.mark.parametrize('cite_rejected', [False, True])
def test_rejected_surplus_is_dropped_but_cannot_complete_any_criterion(cite_rejected):
    class Extra(Gateway):
        def call(self, stage, prompt, body, schema):
            if stage == 'generate':
                return Draft(claims=[dict(claim_id='good', text='저장 판정과 제출 기한 설명', fact_ids=['judgment','document'], source_ids=['judgment','document']),
                                     dict(claim_id='bad', text='근거 없는 추가 설명', fact_ids=['document'], source_ids=['document'])])
            return Verdicts(verdicts=[dict(claim_id='good', status='SUPPORTED', reason='supported'),
                                     dict(claim_id='bad', status='INSUFFICIENT', reason='unsupported')],
                criteria=[dict(criterion_id=c['criterion_id'], status='MET', claim_ids=['bad' if cite_rejected else 'good'], reason='coverage') for c in body['acceptance']])
    state, bundle, plan = setup()
    claims, partial, events = _compose_basic(bundle, plan, state, Extra())
    assert partial is cite_rejected
    assert all(c.claim_id != 'bad' for c in claims)


def test_unresolved_submission_rejection_survives_history_and_requires_same_stage_repair():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation
    from apps.api.app.copilot.v31_contracts import Claim
    from apps.api.app.copilot.answer_progress import (save_review, current_review_context,
        include_repair_criteria, unresolved_repairs, resume_review)
    from apps.api.app.copilot.acceptance import assess_acceptance
    state,bundle,plan=setup()
    row=SubmissionObligation(document='제안서',stage='입찰등록',stage_kind='입찰참가등록',
        obligation='필수',deadline='7월 27일',deadline_kind='절대일시',method='방문',
        timing='예정일 경과',conditions='필수 제출')
    old=Claim(claim_id='old',text='입찰등록 필수 목록: 제안서',fact_ids=['document'],source_ids=['document'],
        validation='SUPPORTED',method='semantic',submission=row)
    save_review(state,'first',[old],None,bundle=bundle)
    rejected=old.model_copy(update={'claim_id':'bad','text':'입찰등록 제출: 제안서',
        'validation':'CONTRADICTED','reason':'입찰등록 목록에서 서약서 누락'})
    save_review(state,'third',[old],None,bundle=bundle,rejected=[rejected])
    assert not current_review_context(state,bundle)[0]
    plan.resume_unresolved=True
    criteria=include_repair_criteria(state,bundle,plan,())
    assert len(criteria)==1 and criteria[0].submission_stage=='입찰참가등록'
    retained,_=resume_review(state,'different',plan,bundle=bundle,criteria=criteria)
    assert not retained
    contract=old.model_copy(update={'claim_id':'new-contract', 'text':'계약 시 서약서',
        'submission':row.model_copy(update={'document':'서약서','stage_kind':'계약체결'})})
    def assess(claim):
        verdict=Verdicts(verdicts=[],criteria=[dict(criterion_id=criteria[0].criterion_id,
            status='MET',claim_ids=[claim.claim_id],reason='model says fixed')])
        return assess_acceptance(criteria,verdict,[claim])
    assert assess(contract)['task_coverage']=='PARTIAL'
    assert assess(old.model_copy(update={'claim_id':'reviewed-1'}))['task_coverage']=='PARTIAL'
    save_review(state,'fourth',[contract],assess(contract),bundle=bundle,criteria=criteria)
    assert unresolved_repairs(state,bundle)
    fixed=old.model_copy(update={'claim_id':'new-registration','text':'입찰등록: 제안서와 서약서',
        'submission':row.model_copy(update={'document':'제안서와 서약서'})})
    assessment=assess(fixed)
    assert assessment['task_coverage']=='COMPLETE'
    save_review(state,'fixed',[fixed],assessment,bundle=bundle,criteria=criteria)
    assert not unresolved_repairs(state,bundle)
    assert old.text not in [c['text'] for c in current_review_context(state,bundle)[0]]
    bundle.sources[-1].quote='changed source'
    assert not current_review_context(state,bundle)[0]
