"""Bounded visit answers become reviewable proposals, never writes."""
import json
import re
from pydantic import BaseModel, ConfigDict, Field
from .contracts import ActionInput
from . import product_tools


class DeclaredField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str
    value: bool | None
    quote: str


class DeclaredAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    factual_answer: bool
    fields: list[DeclaredField] = Field(max_length=12)
    evidence_held: bool = False
    evidence_quote: str = ''


class AnswerMappingClarification(ValueError):
    """An explicit proposal request must not degrade to a successful read."""

    def __init__(self, fields, reason):
        self.reason = reason
        labels = [f.get('label', f['key']) for f in fields]
        super().__init__('답변을 각 조건에 안전하게 연결하지 못해 제안을 만들지 않았습니다. '
                         '다음 조건을 각각 예/아니요로 알려 주세요: '
                         + ' / '.join(labels)
                         + '. 증빙 보유 여부도 알려 주세요. 답변 저장이나 재판정은 하지 않았습니다.')


def structured_candidate(request, state, tools, gateway):
    """Parse declared answers for one freshly offered contract, never execute them.

    The model can map user words to offered fields only. The server selects the
    requirement/basis, requires a quote for each value, and produces the normal
    reviewable proposal. Unknown, hypothetical or ambiguous answers stay unsigned.
    """
    if request.user_input is not None or request.target_id or request.requirement_key:
        return None
    if not getattr(gateway, 'enabled', True) or not state.messages or state.messages[-1].scope != tools.scope:
        return None
    text = request.message
    if (not re.search(r'제안|반영할\s*내용|저장할\s*내용', text)
            or re.search(r'가정|만약|(?:제안|반영)(?:은|을)?\s*(?:하지|하지는)\s*마', text)):
        return None
    recent = {m.turn_id for m in state.messages[-4:] if m.scope == tools.scope}
    offered = [t for t in state.targets if t.message_id in recent
               and t.origin_tool == 'READ_CHECKS' and t.requirement_key]
    # A non-writing hypothetical follow-up does not consume the offered answer
    # target. Reread askability and its current basis before any proposal.
    latest = offered[-1].message_id if offered else None
    keys = {t.requirement_key for t in offered if t.message_id == latest}
    if not keys:
        return None
    summary = tools._summary()
    checks = product_tools.get_required_checks(tools.db, tools.case.id)
    if checks.provenance != summary.provenance:
        raise ValueError('PRODUCT_SCOPE_CHANGED')
    candidates = [q for q in checks.questions if q.askable and q.requirement_key in keys
                  and q.confirmation_fields and q.confirmation_basis]
    if len(candidates) != 1:
        return None
    q = candidates[0]
    try:
        parsed = gateway.call('parse_answer', '''사용자가 앱의 확인 항목에 답변을 제안하도록 요청했다.
현재 메시지에서 사용자가 직접 진술한 사실만 주어진 필드에 대응시킨다. 공고 조건이나 과거 가정을 회사 사실로 바꾸지 않는다.
각 필드의 value는 명시적 긍정 true, 명시적 부정 false, 미언급/모호하면 null이다.
각 quote는 그 값을 뒷받침하는 현재 메시지의 연속된 원문이다. 키를 추가하거나 생략하지 않는다.
추정/가정/타사 정보/질문이면 factual_answer=false다. 증빙도 직접 보유한다고 진술한 경우만 true와 원문을 반환한다.
"아직 실행하지 마"는 검토할 제안을 요청하는 것과 양립한다. 이 도구는 저장하거나 자격을 검증하지 않는다.''',
            {'message': text, 'fields': q.confirmation_fields}, DeclaredAnswer)
    except Exception as exc:
        # Provider/schema failures cannot turn into a guessed answer proposal.
        raise AnswerMappingClarification(q.confirmation_fields, 'PARSER_UNAVAILABLE') from exc
    allowed = {f['key'] for f in q.confirmation_fields}
    if (not parsed.factual_answer or len(parsed.fields) != len(allowed)
            or {f.key for f in parsed.fields} != allowed
            or any(f.value is None or not f.quote.strip() or f.quote not in text for f in parsed.fields)
            or (parsed.evidence_held and (not parsed.evidence_quote.strip() or parsed.evidence_quote not in text))):
        raise AnswerMappingClarification(q.confirmation_fields, 'UNCONFIRMED_FIELD_OR_QUOTE')
    values = {f.key:f.value for f in parsed.fields}
    value = json.dumps({'basis': q.confirmation_basis, 'answers': values}, ensure_ascii=False)
    return q.requirement_key, ActionInput(satisfies_requirement=all(values.values()),
        normalized_value=value, evidence_held=parsed.evidence_held)


def proposal_description(action):
    values = json.loads(action.user_input.normalized_value)['answers']
    if set(values) == {'site_visited', 'visit_certificate'}:
        answer = ('현장 방문 ' + ('완료' if values['site_visited'] else '미완료')
                  + ', 확인서 ' + ('제출' if values['visit_certificate'] else '미제출'))
    else:
        from ..qualification.rules.source_contracts import confirmation_fields
        labels = dict(confirmation_fields({'kind':'WASTE_TRANSPORT'}))
        answer = ' / '.join(labels.get(k, k) + ': ' + ('예' if v else '아니요') for k,v in values.items())
    return (answer + '로 답변을 제안합니다. '
            + ('증빙 보유로 입력했습니다. 실제 증빙을 검증한 것은 아닙니다. ' if action.user_input.evidence_held else '증빙 보유 여부는 확인되지 않았습니다. ')
            + '아직 저장하지 않았습니다. 서버 제안 검토에서 내용을 확인한 뒤 실행할 수 있습니다. 회사 프로필은 변경하지 않습니다.')


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
