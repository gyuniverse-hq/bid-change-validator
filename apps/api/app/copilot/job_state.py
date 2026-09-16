"""Server-owned, scoped requirements across turns; never executes business writes.

A model may bind a task to an existing compatible requirement. It cannot delete
requirements or set their completion. Evidence references are audit receipts,
not facts to be reused by the next generation without reading current tools.
"""
from uuid import uuid4
import hashlib
import json
from .v31_contracts import JobRequirement, JobState, Task

READS = {'READ_JUDGMENT', 'READ_PROFILE', 'READ_CHECKS', 'READ_DOCUMENT', 'READ_CHANGES'}
FINISHED = {'ANSWERED', 'EXECUTED'}


def action_key(action):
    return hashlib.sha256(json.dumps(action.model_dump(mode='json'), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def apply_execution_receipts(state, receipts):
    if state.job is None:
        return
    for requirement in state.job.requirements:
        if (requirement.tool == 'PROPOSE_ACTION' and requirement.action_keys
                and all(key in receipts for key in requirement.action_keys)):
            requirement.status = 'EXECUTED'
            requirement.execution_result_ids = [receipts[key] for key in requirement.action_keys]
            requirement.reason = '명시적으로 확인한 요청의 저장·재판정 API가 성공했습니다. 현재 참가자격은 별도로 조회합니다.'


def planner_context(state):
    if state.job is None:
        return None
    pending = [r for r in state.job.requirements if r.status not in FINISHED]
    done = [r for r in state.job.requirements if r.status in FINISHED]
    visible = (pending + done[-3:])[:12]
    return {'goal': state.job.goal[:600], 'requirements': [
        {'requirement_id': r.requirement_id, 'request': r.request[:120],
         'tool': r.tool, 'status': r.status} for r in visible],
        'additional_requirements_retained': len(state.job.requirements) - len(visible)}


def conversation_hints(state, scope):
    """Hints are deliberately incomplete and never used as factual evidence."""
    return [{'question': m.question[:200], 'answer_hint': m.answer[:200],
             'action_proposed': m.action_proposed}
            for m in state.messages[-2:] if m.scope == scope]


def model_planner_contract(state):
    """Expose short, tool-specific read references, never goal/action UUIDs."""
    from pydantic import create_model,Field
    from typing import Literal,Union,get_args
    from .v31_contracts import TaskPlan
    context=planner_context(state)
    reverse={}
    rows=[]
    if context:
        context=dict(context)
        context['pending_goals']=[{'request':r['request'],'status':r['status']}
                                  for r in context['requirements'] if r['tool']=='GOAL']
        for r in context['requirements']:
            if r['tool'] not in READS:
                continue
            alias='R'+str(len(rows)+1)
            reverse[alias]=r['requirement_id']
            rows.append({**r,'requirement_id':alias})
        context['requirements']=rows
    variants=[]
    for kind in get_args(Task.model_fields['kind'].annotation):
        ids=tuple(r['requirement_id'] for r in rows if r['tool']==kind)
        reference_type=Literal[ids] | None if ids else type(None)
        variants.append(create_model('Planned_'+kind,__base__=Task,
            kind=(Literal[kind],...),requirement_id=(reference_type,None)))
    schema=create_model('ScopedTaskPlan',__base__=TaskPlan,
                        tasks=(list[Union[tuple(variants)]],Field(min_length=1,max_length=6)))
    return context,schema,reverse


def reconcile_basis(state, scope, fingerprints=None):
    if state.job is None:
        return
    for requirement in state.job.requirements:
        if requirement.status == 'EXECUTED':
            continue  # Historical execution receipt, never a current eligibility claim.
        changed = requirement.basis != scope or any(
            key in (fingerprints or {}) and fingerprints[key] != value
            for key, value in requirement.fingerprints.items())
        if changed:
            requirement.status = 'STALE'
            requirement.claim_ids = []
            requirement.source_ids = []
            requirement.reason = '근거 기준이 바뀌어 다시 확인해야 합니다.'
    state.job.status = 'COMPLETE' if state.job.requirements and all(r.status in FINISHED for r in state.job.requirements) else 'OPEN'


def bind_plan(state, plan):
    if state.job is None:
        state.job = JobState(job_id=uuid4(), goal=plan.goal)
    by_id = {r.requirement_id: r for r in state.job.requirements}
    # A completed job has nothing unresolved to resume. A model's resume flag
    # must not replace a new follow-up request with the old completed goal.
    if state.job.status == 'COMPLETE':
        plan.resume_unresolved = False
    if plan.resume_unresolved:
        # The selected follow-up tool is not the scope of the original job.
        # Reread missing dependencies of unresolved compound goals, never writes.
        for goal in state.job.requirements:
            if goal.tool != 'GOAL' or goal.status in FINISHED:
                continue
            for read in goal.required_reads:
                if read.kind in READS and not any(t.kind == read.kind for t in plan.tasks):
                    if len(plan.tasks) >= 6:
                        continue  # Preserve pending goal; do not exceed the execution contract.
                    plan.tasks.append(read.model_copy(update={'requirement_id': None}))
    if len({t.kind for t in plan.tasks}) > 1:
        goal = next((r for r in state.job.requirements if r.tool == 'GOAL' and r.request == plan.goal), None)
        if goal is None:
            if len(state.job.requirements) >= 40:
                raise ValueError('JOB_REQUIREMENT_LIMIT')
            goal = JobRequirement(requirement_id='goal-' + str(uuid4()), request=plan.goal,
                                  tool='GOAL', basis=state.scope,
                                  reason='원래 요청 전체의 설명을 확인해야 합니다.',
                                  required_reads=[t.model_copy(update={'requirement_id': None})
                                                  for t in plan.tasks if t.kind in READS])
            state.job.requirements.append(goal)
    # Resume reads only. A pending action is never replayed by job resumption.
    if plan.resume_unresolved:
        for task in plan.tasks:
            candidates = [r for r in state.job.requirements if r.tool == task.kind and r.status not in FINISHED]
            if task.requirement_id is None and len(candidates) == 1 and task.kind in READS:
                task.requirement_id = candidates[0].requirement_id
        # Multiple requests can use one tool (e.g. document summary followed by
        # a consolidated checklist). A model binding to one does not cover the
        # others. Reread each pending request explicitly; never replay actions.
        for requirement in state.job.requirements:
            if requirement.tool not in READS or requirement.status in FINISHED:
                continue
            if any(t.requirement_id == requirement.requirement_id for t in plan.tasks):
                continue
            if len(plan.tasks) >= 6:
                break  # Unscheduled requirements remain OPEN, never assumed done.
            plan.tasks.append(Task(kind=requirement.tool,question=requirement.request,
                                   requirement_id=requirement.requirement_id))
    bindings = []
    for task in plan.tasks:
        # Acknowledgement is a procedure, not completion of a pending action.
        if task.kind == 'ACKNOWLEDGE_ACTION':
            task.requirement_id = None
            continue
        requirement = by_id.get(task.requirement_id)
        if requirement is not None and requirement.tool != task.kind:
            raise ValueError('JOB_REQUIREMENT_TOOL_MISMATCH')
        if task.requirement_id and requirement is None:
            raise ValueError('UNKNOWN_JOB_REQUIREMENT')
        if requirement is None:
            requirement = next((r for r in state.job.requirements
                                if r.tool == task.kind and r.request == task.question), None)
        if requirement is None:
            if len(state.job.requirements) >= 40:
                raise ValueError('JOB_REQUIREMENT_LIMIT')
            requirement = JobRequirement(requirement_id='r-' + str(uuid4()),
                request=task.question, tool=task.kind, basis=state.scope)
            state.job.requirements.append(requirement)
            by_id[requirement.requirement_id] = requirement
        task.requirement_id = requirement.requirement_id
        bindings.append((task, requirement))
    return bindings


def include_job_criteria(state, plan, bundle, criteria):
    """Freeze original goals beside the current deliverable, with fresh evidence."""
    from .v31_contracts import AcceptanceCriterion
    if not state or not state.job:
        return tuple(criteria), []
    result, bindings = list(criteria), []
    for goal in state.job.requirements:
        if goal.tool != 'GOAL':
            continue
        current = goal.request == plan.goal
        if not current and not (plan.resume_unresolved and goal.status not in FINISHED):
            continue
        cid = 'GOAL:request' if current and any(c.criterion_id == 'GOAL:request' for c in result) else 'GOAL:' + goal.requirement_id
        if not any(c.criterion_id == cid for c in result):
            result.append(AcceptanceCriterion(criterion_id=cid, task_kind='GOAL', mode='EXPLANATION',
                requirement='이어갈 원래 요청: ' + goal.request +
                ' 이미 검증한 설명과 이번 설명을 함께 평가한다. 남은 부분을 빠뜨리면 MISSING이다. '
                '확인할 일 안내 요청에 실제 증빙 확보나 실행을 완료 조건으로 추가하지 않는다.',
                fact_ids=tuple(f.fact_id for f in bundle.facts)))
        bindings.append({'criterion_id': cid, 'requirement_id': goal.requirement_id})
    return tuple(result), bindings


def finish_turn(state, bindings, bundle, claims, events, *, complete, turn_id, actions):
    """Promote only a complete turn or independently assessed task criteria."""
    from .answer_progress import latest_assessment
    assessment = latest_assessment(events)
    definitions = next((e['criteria'] for e in events if e.get('stage') == 'acceptance'), [])
    assessed = bool(assessment and 'reason' not in assessment)
    missing = set(assessment.get('missing_criterion_ids', [])) if assessed else set()
    from .answer_validation import UNSAFE_REASONS
    rejected = [e for e in events if e.get('validation') == 'CONTRADICTED' or e.get('reason') in UNSAFE_REASONS]
    complete = complete and not rejected
    def remaining_label(criterion):
        if criterion.get('mode') == 'CHECKLIST':
            basis = next((f for f in bundle.facts if f.fact_id in criterion.get('fact_ids', [])), None)
            if basis:
                text = basis.text.split('\n', 1)[-1]
                return '확인할 조건의 설명 검증: ' + text[:240] + ('… (원문에서 전체 확인)' if len(text) > 240 else '')
        return criterion['requirement']
    for task, requirement in bindings:
        facts = {f.fact_id for f in bundle.facts if f.origin_tool == task.kind}
        supported = [c for c in claims if c.validation == 'SUPPORTED' and facts.intersection(c.fact_ids)]
        requirement.basis = bundle.scope.model_copy(deep=True)
        requirement.fingerprints = dict(bundle.fingerprints)
        requirement.last_turn_id = turn_id
        requirement.claim_ids = [c.claim_id for c in supported]
        requirement.source_ids = list(dict.fromkeys(s for c in supported for s in c.source_ids))
        task_criteria = [c for c in definitions if c.get('task_kind') == task.kind]
        rows = {r['criterion_id'] for r in assessment.get('criteria', [])} if assessed else set()
        task_complete = (assessed and bool(task_criteria) and bundle.coverage.get(task.kind) == 'FOUND'
                         and all(c['criterion_id'] in rows and c['criterion_id'] not in missing for c in task_criteria)
                         and not rejected and not any(e.get('reason') == 'EVIDENCE_BUDGET' for e in events))
        requirement.remaining = [remaining_label(c) for c in task_criteria
                                 if not assessed or c['criterion_id'] in missing or c['criterion_id'] not in rows]
        if task.kind == 'PROPOSE_ACTION':
            requirement.action_keys = [action_key(action) for action in actions]
            requirement.execution_result_ids = []
            requirement.status = 'AWAITING_CONFIRMATION' if actions else 'OPEN'
            requirement.reason = '사용자 확인과 실제 실행 결과가 필요합니다.'
        elif (complete or task_complete) and supported and task.kind in READS:
            requirement.status = 'ANSWERED'
            requirement.reason = '현재 기준에서 요청한 설명을 검증했습니다. 현실 자격이나 실행 완료를 뜻하지 않습니다.'
        elif complete and task.kind == 'REVIEW_ASSUMPTION' and any(f.kind == 'ASSUMPTION' for f in bundle.facts):
            requirement.status = 'ANSWERED'
            requirement.reason = '가정 검토 설명만 완료했으며 저장하지 않았습니다.'
        else:
            requirement.status = 'UNAVAILABLE' if bundle.coverage.get(task.kind) in {'UNAVAILABLE', 'NOT_FOUND'} else 'OPEN'
            requirement.reason = ('현재 자료를 읽을 수 없습니다. 원문 화면 또는 자료 제공 여부를 확인해 주세요.'
                                  if requirement.status == 'UNAVAILABLE' else
                                  '아래 항목의 설명을 충분히 검증하지 못했습니다. 이어서 검토하거나 원문에서 확인해 주세요.')
    if state.job:
        goal_bindings = [b for e in events if e.get('stage') == 'job_goal_binding' for b in e['bindings']]
        verdicts = {r['criterion_id']: r for r in (assessment or {}).get('criteria', [])}
        for binding in goal_bindings:
            goal = next((r for r in state.job.requirements if r.requirement_id == binding['requirement_id']), None)
            if goal is None:
                continue
            row = verdicts.get(binding['criterion_id'])
            met = assessed and row and row['status'] == 'MET' and binding['criterion_id'] not in missing and not rejected
            goal.status = 'ANSWERED' if met else 'OPEN'
            goal.basis, goal.fingerprints = bundle.scope.model_copy(deep=True), dict(bundle.fingerprints)
            goal.last_turn_id = turn_id
            goal.reason = ('원래 요청의 설명을 확인했습니다. 실제 준비·증빙 확보·저장을 뜻하지 않습니다.' if met else
                           (row or {}).get('reason') or '원래 요청 전체의 설명을 아직 확인하지 못했습니다.')
            goal.remaining = [] if met else [goal.reason]
        if rejected:
            reason = '설명과 근거의 불일치를 보완해야 합니다: ' + '; '.join(e.get('reason', '') for e in rejected)[:500]
            for _, requirement in bindings:
                if requirement.status not in FINISHED:
                    requirement.remaining = list(dict.fromkeys([*requirement.remaining, reason]))
        state.job.revision += 1
        state.job.remaining = list(dict.fromkeys(
            item for requirement in state.job.requirements if requirement.status not in FINISHED
            for item in (requirement.remaining or [requirement.reason or requirement.request])))
        state.job.status = 'COMPLETE' if complete and state.job.requirements and all(r.status in FINISHED for r in state.job.requirements) else 'OPEN'
