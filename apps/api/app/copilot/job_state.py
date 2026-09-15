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
    # Resume reads only. A pending action is never replayed by job resumption.
    if plan.resume_unresolved:
        for task in plan.tasks:
            candidates = [r for r in state.job.requirements if r.tool == task.kind and r.status not in FINISHED]
            if task.requirement_id is None and len(candidates) == 1 and task.kind in READS:
                task.requirement_id = candidates[0].requirement_id
            if task.requirement_id in by_id and task.kind in READS:
                task.question = by_id[task.requirement_id].request
        planned_ids = {t.requirement_id for t in plan.tasks}
        for requirement in state.job.requirements:
            if len(plan.tasks) >= 6:
                break
            if requirement.tool in READS and requirement.status != 'ANSWERED' and requirement.requirement_id not in planned_ids:
                plan.tasks.append(Task(kind=requirement.tool, question=requirement.request,
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


def finish_turn(state, bindings, bundle, claims, events, *, complete, turn_id, actions):
    """Conservative: a partial turn cannot promote requested requirements.

No source ID alone establishes semantic completeness. Only the existing
generation/validation/coverage result can qualify the current response, and an
action proposal remains pending even if its explanation passed.
"""
    for task, requirement in bindings:
        facts = {f.fact_id for f in bundle.facts if f.origin_tool == task.kind}
        supported = [c for c in claims if c.validation == 'SUPPORTED' and facts.intersection(c.fact_ids)]
        requirement.basis = bundle.scope.model_copy(deep=True)
        requirement.fingerprints = dict(bundle.fingerprints)
        requirement.last_turn_id = turn_id
        requirement.claim_ids = [c.claim_id for c in supported]
        requirement.source_ids = list(dict.fromkeys(s for c in supported for s in c.source_ids))
        if task.kind == 'PROPOSE_ACTION':
            requirement.action_keys = [action_key(action) for action in actions]
            requirement.execution_result_ids = []
            requirement.status = 'AWAITING_CONFIRMATION' if actions else 'OPEN'
            requirement.reason = '사용자 확인과 실제 실행 결과가 필요합니다.'
        elif complete and supported and task.kind != 'REVIEW_ASSUMPTION':
            requirement.status = 'ANSWERED'
            requirement.reason = '현재 기준에서 요청한 설명을 검증했습니다. 현실 자격이나 실행 완료를 뜻하지 않습니다.'
        elif complete and task.kind == 'REVIEW_ASSUMPTION' and any(f.kind == 'ASSUMPTION' for f in bundle.facts):
            requirement.status = 'ANSWERED'
            requirement.reason = '가정 검토 설명만 완료했으며 저장하지 않았습니다.'
        else:
            requirement.status = 'UNAVAILABLE' if bundle.coverage.get(task.kind) in {'UNAVAILABLE', 'NOT_FOUND'} else 'OPEN'
            requirement.reason = '근거 또는 답변 검증이 충분하지 않아 남은 요청으로 유지합니다.'
    if state.job:
        state.job.revision += 1
        state.job.status = 'COMPLETE' if state.job.requirements and all(r.status in FINISHED for r in state.job.requirements) else 'OPEN'
