"""Bounded visit answers become reviewable proposals, never writes."""
import json
import re
from .contracts import ActionInput
from . import product_tools


def visit_values(message):
    # Full-string grammar deliberately rejects assumptions, questions, partial
    # answers, conflicting clauses and additional instructions.
    compact = re.sub(r'\s+', '', message).rstrip('.!。')
    # An exact preview suffix authorizes a proposal, never persistence.
    compact = re.sub(r'[.!。]이답변을반영하면무엇이바뀌는지먼저보여줘[.!。]아직저장하지마$', '', compact)
    match = re.fullmatch(
        r'현장방문(?:은|을)?(완료했(?:지만|고)|하지않았(?:지만|고))[,]?'
        r'(?:현장방문)?확인(?:서|증)(?:는|를)?(?:아직)?'
        r'(제출하지않았어|미제출이야|제출했어|제출완료했어)', compact)
    if not match:
        return None
    return {'site_visited': match[1].startswith('완료'),
            'visit_certificate': match[2] in {'제출했어', '제출완료했어'}}


def visit_candidate(request, state, tools):
    if request.user_input is not None or request.target_id or request.requirement_key:
        return None
    values = visit_values(request.message)
    if values is None or not state.messages or state.messages[-1].scope != tools.scope:
        return None
    # Only accept an answer to a check actually offered in the latest turn.
    latest = state.messages[-1].turn_id
    keys = {t.requirement_key for t in state.targets
            if t.message_id == latest and t.origin_tool == 'READ_CHECKS' and t.requirement_key}
    if not keys:
        return None
    summary = tools._summary()
    checks = product_tools.get_required_checks(tools.db, tools.case.id)
    if checks.provenance != summary.provenance:
        raise ValueError('PRODUCT_SCOPE_CHANGED')
    candidates = [q for q in checks.questions if q.askable and q.requirement_key in keys
                  and {f['key'] for f in q.confirmation_fields} == set(values)
                  and q.confirmation_basis]
    if len(candidates) != 1:
        return None
    q = candidates[0]
    value = json.dumps({'basis': q.confirmation_basis, 'answers': values}, ensure_ascii=False)
    return q.requirement_key, ActionInput(satisfies_requirement=all(values.values()),
                                         normalized_value=value, evidence_held=False)
