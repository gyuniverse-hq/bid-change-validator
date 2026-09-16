"""Render every proposed obligation field before semantic verification.

Rows are model proposals, never authoritative extraction or persisted eligibility.
The same document at two stages remains two independently cited claims.
"""
from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, Field


class SubmissionObligation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document: str = Field(min_length=1, max_length=500)
    stage: str = Field(min_length=1, max_length=200)
    obligation: Literal['필수', '협조', '조건부', '확인 필요']
    deadline: str = Field(min_length=1, max_length=300)
    method: str = Field(min_length=1, max_length=300)
    timing: Literal['예정일 경과', '예정', '시점 미확정']
    conditions: str = Field(min_length=1, max_length=600)
    stage_kind: Literal['설명회', '입찰참가등록', '가격입찰', '제안발표', '선정후', '계약체결', '이행', '기타', '미확정'] = '미확정'
    deadline_kind: Literal['절대일시', '사건기준', '미기재'] = '미기재'
    anchor_event: str | None = Field(default=None, max_length=200)


def render_obligation(row: SubmissionObligation) -> str:
    # Nothing from a structured row bypasses the existing claim verifier.
    return (f'[{row.stage} · {row.obligation}] {row.document}\n'
            f'기한: {row.deadline} ({row.timing}) · 제출 방법: {row.method}\n'
            f'조건·확인할 일: {row.conditions}')


def preserve_requirement_exclusions(text, fact_ids, bundle):
    """Keep literal exclusions in a paraphrase of one stored requirement.

    Only that requirement's short, directly attached document excerpt is used.
    The augmented candidate still goes through normal semantic verification.
    """
    facts = {f.fact_id:f for f in bundle.facts}
    requirements = [facts[fid] for fid in fact_ids if fid in facts
        and facts[fid].origin_tool == 'READ_JUDGMENT' and facts[fid].requirement_key]
    if len(requirements) != 1 or not re.search(r'요건|조건|기준|실적', text):
        return text
    attached = set(requirements[0].source_ids)
    terms = []
    normalize = lambda value: re.sub(r'\s+','',value)
    for source in bundle.sources:
        if (source.source_id not in attached or source.kind != 'DOCUMENT'
                or source.scope != requirements[0].scope or len(source.quote)>1500):
            continue
        for term in re.findall(r'\(([^()\n]{2,140}제외)\)', source.quote):
            if normalize(term) not in normalize(text) and term not in terms:
                terms.append(term)
    if not terms:
        return text
    return text + ' 해당 요건의 원문 제외 조건: ' + ' / '.join('“'+term+'”' for term in terms) + '.'


def expand_submission_references(fact_ids, bundle):
    """Citing an annex table also needs its explicit submission-clause reference.

    One-level citation closure within the exact same document and scope. This
    adds source evidence, not a verdict or an inferred legal phase.
    """
    sources = {s.source_id: s for s in bundle.sources if s.kind == 'DOCUMENT' and s.document_id}
    facts = {f.fact_id: f for f in bundle.facts if f.origin_tool == 'READ_DOCUMENT'}
    definitions = set()
    for fid in fact_ids:
        if fid not in facts:
            continue
        for sid in facts[fid].source_ids:
            source = sources.get(sid)
            if source is None:
                continue
            for label in re.findall(r'^\s*<\s*((?:별첨|붙임|첨부)\s*\d+)\s*>[^\n]*(?:제출|자료)', source.quote, re.M):
                definitions.add((source.document_id, source.scope.model_dump_json(), re.sub(r'\s+', '', label)))
    expanded = list(fact_ids)
    for fact in bundle.facts:
        if fact.fact_id in expanded or fact.origin_tool != 'READ_DOCUMENT':
            continue
        for sid in fact.source_ids:
            source = sources.get(sid)
            if source is None:
                continue
            labels = re.findall(r'제출\s*서류\s*[:：]\s*<\s*((?:별첨|붙임|첨부)\s*\d+)\s*>', source.quote)
            if any((source.document_id, source.scope.model_dump_json(), re.sub(r'\s+', '', label)) in definitions for label in labels):
                expanded.append(fact.fact_id)
                break
    return expanded


def referenced_stage_obligations(bundle, explicit):
    """Keep a named document's additional, explicitly referenced table stage.

    A contract submission does not discharge a separately referenced proposal
    submission list. Only exact same-document annex references are supported.
    This freezes what needs explaining; it never supplies a qualified verdict.
    """
    facts={f.fact_id:f for f in bundle.facts if f.origin_tool=='READ_DOCUMENT'}
    sources={s.source_id:s for s in bundle.sources if s.kind=='DOCUMENT'}
    normalize=lambda text:re.sub(r'\s+','',text)
    def table_names(quote):
        # A document mentioned in surrounding contract prose is not a table
        # member. Require a named row followed by its count and form reference.
        heading=re.search(r'^\s*<\s*(?:별첨|붙임|첨부)\s*\d+\s*>[^\n]*(?:제출|자료)',quote,re.M)
        if not heading:
            return set()
        table=re.split(r'^\s*<\s*(?:별첨|붙임|첨부)',quote[heading.end():],maxsplit=1,flags=re.M)[0]
        return {normalize(name) for name in re.findall(
            r'^[ \t]*([가-힣A-Za-z· ()]{2,60})[ \t]*\n[ \t]*\d+[ \t]*\n[ \t]*\[별지[ \t]*제[ \t]*\d+[ \t]*호[ \t]*서식\]',
            table,re.M)}
    result=[]
    for anchor in explicit:
        for fact in facts.values():
            if not any(sid in sources and normalize(anchor['document']) in table_names(sources[sid].quote)
                       for sid in fact.source_ids):
                continue
            expanded=expand_submission_references([fact.fact_id],bundle)
            parents=[fid for fid in expanded[1:] if any(
                re.search(r'(?:^|\n)\s*(?:[가-힣0-9]+\.\s*)?(?:제안서\s*제출|입찰\s*참가\s*등록)(?:\s|$)',sources[sid].quote)
                for sid in facts[fid].source_ids if sid in sources)]
            if parents and anchor['stage']!='입찰참가등록':
                result.append({'document':anchor['document'],'stage':'입찰참가등록',
                               'fact_ids':[fact.fact_id,*parents]})
    unique={ (a['stage'],a['document']):a for a in result }
    return list(unique.values())


def structural_error(row):
    if row is None:
        return None
    if row.obligation != '확인 필요' and re.search(r'기타\s*서류|공고상\s*서류', row.document):
        return 'UNRESOLVED_DOCUMENT_LIST'
    if row.deadline_kind == '사건기준' and (not row.anchor_event or row.timing != '시점 미확정'):
        return 'RELATIVE_DEADLINE_WITHOUT_CONFIRMED_EVENT'
    if row.deadline_kind != '사건기준' and row.anchor_event:
        return 'DEADLINE_ANCHOR_KIND_MISMATCH'
    return None


def normalize_event_timing(row):
    """Do not turn an unobserved submission/award into a past event.

    Only weaken an event-relative label. Keep date text and the event anchor;
    a calendar date in the same field does not prove that the event occurred.
    The resulting full row still requires semantic source verification.
    """
    if row is not None and row.deadline_kind == '미기재' and row.anchor_event:
        # "No exact date" can still have an explicitly named relative event.
        # Keep that event, do not invent its occurrence date or mark it past.
        row = row.model_copy(update={'deadline_kind':'사건기준','timing':'시점 미확정'})
    if (row is not None and row.deadline_kind == '사건기준' and row.anchor_event
            and re.search(r'(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}[-./]\d{1,2}[-./]\d{1,2}', row.deadline)
            and re.search(r'(?:시간|시각).*(?:개별\s*통보|추후\s*통보|미정)', row.deadline)
            and not re.search(r'이후|이전|다음|부터|선정\s*후|종료\s*후|체결\s*전|\d+\s*일\s*(?:전|후)', row.deadline)):
        # A specified calendar day is not made event-relative by an unknown
        # clock time. "예정일 경과" still does not mean attendance occurred.
        # The full dated claim remains subject to source verification.
        return row.model_copy(update={'deadline_kind':'절대일시','anchor_event':None})
    if row is not None and row.deadline_kind == '사건기준' and row.anchor_event:
        return row.model_copy(update={'timing': '시점 미확정'})
    return row


def preserve_document_quantities(row, quotes):
    """Preserve unambiguous literal counts for documents actually named in a row.

    Conflicting counts stay unresolved. This only supplies proposed source text
    before verification; it does not decide which phase requires the document.
    """
    if row is None:
        return row
    counts = {}
    conditional = set()
    for quote in quotes:
        for name in re.findall(r'\(?\s*필요\s*시\s*\)?\s*([가-힣A-Za-z]{2,30})', quote):
            if re.search(rf'(?<![가-힣A-Za-z]){re.escape(name)}(?![가-힣A-Za-z])', row.document):
                conditional.add(name)
        for name, number, unit in re.findall(r'([가-힣A-Za-z]{2,30})\s*(\d{1,3})\s*(부|매)(?![가-힣])', quote):
            if re.search(rf'(?<![가-힣A-Za-z]){re.escape(name)}(?![가-힣A-Za-z])', row.document):
                counts.setdefault(name, set()).add(f'{number}{unit}')
    extra = [f'{name} {next(iter(values))}' for name, values in counts.items()
             if len(values) == 1 and not re.search(rf'{re.escape(name)}\s*{re.escape(next(iter(values)))}', row.document+' '+row.conditions)]
    conditions = row.conditions + ('; 원문 제출부수: ' + ' / '.join(extra) if extra else '')
    for name in sorted(conditional):
        # Copy the source's optional qualifier along with its count. A grouped
        # mandatory row must not silently make every member mandatory.
        qualifier = f'{name} 제출 조건: 필요시'
        if qualifier not in conditions:
            conditions += '; ' + qualifier
    return row.model_copy(update={'conditions': conditions}) if len(conditions) <= 600 else row


def preserve_form_identity(row, quotes):
    """Distinguish equally suffixed forms using the cited table's exact names."""
    if row is None:
        return row
    forms = {}
    pattern = re.compile(r'^[ \t]*([가-힣A-Za-z· ()]{2,60})[ \t]*\n'
                         r'(?:[ \t]*\d+[ \t]*\n)?[ \t]*\[(별지[ \t]*제[ \t]*\d+[ \t]*호[ \t]*서식)\]', re.M)
    for quote in quotes:
        for name, form in pattern.findall(quote):
            forms.setdefault(' '.join(name.split()), set()).add(' '.join(form.split()))
    parts = re.split(r'([;,])', row.document)
    for i in range(0, len(parts), 2):
        name = ' '.join(parts[i].split())
        values = forms.get(name, set())
        if len(values) == 1:
            parts[i] = parts[i] + ' [' + next(iter(values)) + ']'
    document = ''.join(parts)
    return row.model_copy(update={'document': document}) if len(document) <= 500 else row


def preserve_guarantee_validity(row, quotes):
    """Keep a cited guarantee's explicit expiry condition separate from submission.

    Never calculate an expiry date or resolve competing periods. The resulting
    source proposal still passes through the full claim verifier.
    """
    if row is None or '보증' not in row.document:
        return row
    periods = set()
    for quote in quotes:
        for line in quote.splitlines():
            match = re.search(r'보증기간(?:의)?\s*만료일[^\n]{1,200}', line)
            if match:
                periods.add(' '.join(match.group().split()))
    if len(periods) != 1:
        return row
    period = next(iter(periods))
    if re.sub(r'\s+', '', period) in re.sub(r'\s+', '', row.conditions):
        return row
    conditions = row.conditions + '; 원문 유효기간 조건: ' + period
    return row.model_copy(update={'conditions': conditions}) if len(conditions) <= 600 else row


def distinguish_submission_recipient(row, quotes):
    """An explicitly named approval authority does not prove a filing recipient.

    Only weaken the narrow observed confusion; other destinations still need
    source verification. This does not assert the whole document lacks a venue.
    """
    if row is None:
        return row
    match=re.match(r'([가-힣A-Za-z ]{2,40})에게\s*제출(?=$|[ ,;.]|하)',row.method.strip())
    if not match:
        return row
    recipient=re.sub(r'\s+','',match[1])
    receipt_terms=(recipient+'에게제출',recipient+'에제출',recipient+'으로제출',
                   '제출처:'+recipient,'제출처：'+recipient)
    known=[]
    receipt_scopes=[]
    approval_only=False
    for quote in quotes:
        text=re.sub(r'\s+','',quote)
        receipt=any(term in text for term in receipt_terms)
        if receipt:
            receipt_scopes.append(text)
        approval=recipient+'의승인' in text or recipient+'승인' in text
        approval_only |= approval and not receipt
        for line in quote.splitlines():
            if any(term in re.sub(r'\s+','',line) for term in receipt_terms):
                known.append(' '.join(line.split()))
    members=[re.sub(r'\s+','',part) for part in re.split(r'[;,]|\s+및\s+',row.document) if part.strip()]
    unbound_members=(len(members)>1 and not all(any(member in text for text in receipt_scopes) for member in members))
    if approval_only or unbound_members:
        method='인용 근거만으로 제출받는 담당자를 확정하지 못했습니다. 발주기관에 제출처 확인이 필요합니다.'
        # A different document's explicit recipient cannot discharge this gap.
        # Retain the known clause literally rather than attach its recipient to
        # every member of the model-proposed bundle. Normal verification follows.
        if known:
            quoted=' / '.join(dict.fromkeys(known))
            method=f'제출처가 명시된 근거: “{quoted}”. 나머지 서류의 제출처는 별도 확인이 필요합니다.'
            if len(method)>300:
                method='인용 근거 중 일부에만 제출처가 명시되어 있습니다. 서류별 제출처를 구분하여 발주기관에 확인해야 합니다.'
        return row.model_copy(update={'method':method})
    return row


def explicit_validity_conditions(bundle, goal):
    """Literal freshness restrictions attached to a named supporting document.

    Limited to an explicit parenthetical recent-month condition. This does not
    infer document validity from an unrelated business-performance period.
    """
    if not any(word in goal for word in ('서류', '준비', '체크리스트')):
        return []
    sources = {s.source_id: s for s in bundle.sources if s.kind == 'DOCUMENT'}
    pattern = re.compile(r'^[ \t]*[-○❍•]?[ \t]*(?P<document>[가-힣0-9 ·]{2,80}'
                         r'(?:증명서|증명\s*자료|확인서))[ \t]*'
                         r'\((?P<term>최근\s*\d+\s*개월\s*이내)\)', re.M)
    found = {}
    for fact in bundle.facts:
        if fact.origin_tool != 'READ_DOCUMENT':
            continue
        for sid in fact.source_ids:
            if sid not in sources:
                continue
            for match in pattern.finditer(sources[sid].quote):
                document, term = ' '.join(match['document'].split()), ' '.join(match['term'].split())
                entry = found.setdefault((document, term), {'document': document, 'term': term, 'fact_ids': []})
                if fact.fact_id not in entry['fact_ids']:
                    entry['fact_ids'].append(fact.fact_id)
    return list(found.values())


def explicit_stage_obligations(bundle, goal):
    """Bounded literal source anchors, not a claim to extract every obligation.

    Match an explicitly named document submitted at a named stage in one clause.
    Never infer a deadline from an unrelated paragraph or an expected Golden row.
    """
    if not any(word in goal for word in ('서류', '준비', '체크리스트')):
        return []
    sources = {s.source_id: s for s in bundle.sources if s.kind == 'DOCUMENT'}
    pattern = re.compile(
        r'(?P<stage>계약\s*체결|입찰\s*참가\s*등록|설명회)\s*시(?:에)?\s*'
        r'(?:첨부된\s*)?(?:\[[^\]\n]{1,60}\]\s*)?'
        r'(?P<document>[가-힣A-Za-z][가-힣A-Za-z·\s]{1,70}?(?:서|증))(?:을|를)\s*제출(?:하여야|해야|한다)')
    found = {}
    for fact in bundle.facts:
        if fact.origin_tool != 'READ_DOCUMENT':
            continue
        for sid in fact.source_ids:
            source = sources.get(sid)
            if source is None:
                continue
            for match in pattern.finditer(source.quote):
                stage = re.sub(r'\s+', '', match['stage'])
                document = ' '.join(match['document'].split())
                key = (stage, re.sub(r'\s+', '', document))
                found.setdefault(key, {'stage':stage, 'document':document, 'fact_ids':[]})
                if fact.fact_id not in found[key]['fact_ids']:
                    found[key]['fact_ids'].append(fact.fact_id)
    return list(found.values())


def preserve_explicit_validity(draft, bundle, criteria):
    """Keep literal document-name/freshness pairs before semantic verification.

    These are quotations from the current source, not inferred equivalence of
    forms, submission deadlines, or company evidence. The verifier still checks
    every added candidate and may reject it; no acceptance status is assigned.
    """
    import hashlib
    from .v31_contracts import Draft, DraftClaim
    facts={f.fact_id:f for f in bundle.facts}
    normalize=lambda text:re.sub(r'\s+','',text)
    result=list(draft.claims)
    for anchor in explicit_validity_conditions(bundle,'제출 서류'):
        terms=(anchor['document'],anchor['term'])
        active=[c for c in criteria if c.task_kind=='READ_DOCUMENT'
                and c.source_required_terms==terms]
        if not active:
            continue
        ids=[fid for fid in anchor['fact_ids'] if any(fid in c.fact_ids for c in active)]
        if not ids or any(set(ids).intersection(c.fact_ids)
                          and all(normalize(term) in normalize(c.text) for term in terms)
                          for c in result):
            continue
        if len(result)>=60:
            break  # Leave the missing criterion unresolved rather than truncate.
        cid='source-validity-'+hashlib.sha256('|'.join(terms).encode()).hexdigest()[:12]
        if any(c.claim_id==cid for c in result):
            continue
        result.append(DraftClaim(claim_id=cid,
            text=f'인용 문서의 제출자료 표기: “{anchor["document"]}({anchor["term"]})”.',
            fact_ids=ids,source_ids=list(dict.fromkeys(sid for fid in ids for sid in facts[fid].source_ids)),
            speech_act='ASSERTION'))
    return Draft(claims=result)


def preserve_parenthetical_qualifiers(row, quotes):
    """Keep explicit source qualifications on the same named subject.

    This is source text preservation, not a second semantic verdict. Only a
    verbatim subject in conditions and an unambiguous normative parenthesis are
    eligible. Ambiguous/different subjects are left to the normal verifier.
    """
    if row is None:
        return row
    qualifiers = {}
    for quote in quotes:
        for match in re.finditer(r'([가-힣A-Za-z]{2,30})\s*(\([^()\n]{1,120}\))', quote):
            subject, qualifier = match.groups()
            if re.search(r'가능|허용|제외|한함|불가', qualifier):
                qualifiers.setdefault(subject, set()).add(qualifier)
    conditions = row.conditions
    for subject, values in qualifiers.items():
        if len(values) != 1:
            continue
        qualifier = next(iter(values))
        if re.sub(r'\s+', '', qualifier) in re.sub(r'\s+', '', conditions):
            continue
        # A differing parenthesis is not replaced or silently resolved.
        pattern = (rf'(?<![가-힣A-Za-z]){re.escape(subject)}'
                   r'(?=(?:은|는|이|가|의|만|만의)?(?:\s|[,.]|$))(?!\s*\()')
        conditions = re.sub(pattern, lambda m: m.group(0) + qualifier, conditions)
    if len(conditions) > 600:
        return row  # Mechanical verification will reject the unpreserved row.
    return row.model_copy(update={'conditions': conditions})


INSTRUCTIONS = '''
제출 서류·참석 준비물은 submission으로 구조화한다. 일반 설명은 submission=null이다.
서류(같은 단계·기한·방법·의무인 서류 묶음 가능), 제출 단계, 필수/협조/조건부/확인 필요,
기한, 방법, 예정일 상태, 예외·확인할 일을 각각 원문 근거로 작성한다.
제출할 서류명은 같은 단계 묶음 안에 모두 남긴다. 사업자등록증·면허 등 별도 서류를 '기타 서류'로 대신하지 않는다. 생략 가능한 것은 서식 내부 작성 목차이며 제출 서류 자체가 아니다. 원문 자체가 미정이면 확인 필요로 표시한다.
서약서처럼 이름 일부가 같은 서류도 정식 명칭과 별지 서식 번호가 다르면 구분한다. 여러 단계의 서류를 모은 전체 제출자료 목록을 한 제출 단계라고 추정하지 않는다. 부수·USB 개수도 각 해당 서류에 보존한다.
다른 절이 그 별첨을 제출서류 목록으로 직접 참조하면 해당 절도 함께 근거로 선택한다. '계약체결 시 제출'은 '계약체결 때만 제출'이라는 뜻이 아니다. 다른 단계의 명시적 참조·의무와 함께 확인한다.
참석자·대상 업체 등에 붙은 괄호 속 허용/제외 조건도 conditions에 원문대로 보존한다.
같은 서류가 입찰과 계약에 모두 등장하면 각 단계별 별도 claim으로 남긴다.
stage_kind는 한 제출 사건만 선택한다. 선정 후와 계약체결은 다른 사건이다.
서류 묶음에 제출 단계/기한/방법/의무가 다른 서류를 합치지 않는다.
deadline_kind는 날짜가 명시되면 절대일시, 선정 후/계약 전/개별 통보이면 사건기준, 없으면 미기재이다.
사건기준은 anchor_event에 기준 사건을 적고 timing=시점 미확정으로 쓴다. 예정된 행사일로 실제 발생일을 만들어내지 않는다.
일반 참가자격이나 관련 제출 항목을 각 서류의 강제 선행 조건으로 변환하지 않는다. 원문이 해당 제출의 선행 조건을 명시한 경우에만 conditions에 그 문구를 설명한다. 같은 마감까지 제출한다는 사실은 제출 순서의 근거가 아니다. 제안하는 준비 순서는 원문상 강제 순서와 구별한 별도 설명으로 작성한다.
보증서의 제출 마감과 보증기간 만료 조건을 구별한다. 명시된 유효기간 조건을 conditions에 보존하고 실제 기준 사건이 확인되지 않으면 만료 날짜를 계산하지 않는다.
한 단계의 기재가 다른 단계의 의무를 없애지 않는다. 실제 상충은 확인 필요로 표시한다.
날짜나 방법이 없으면 원문에 미기재라고 쓰고 추측하지 않는다.
예정일 경과는 행사 개최·참석·제출 완료를 뜻하지 않는다. 실제 이행은 확인할 일로 남긴다.
서버가 submission의 모든 필드를 표시 문장으로 변환해 검증하므로 text에 다른 사실을 추가하지 않는다.
필수와 협조는 별도 claim으로 나누고 단계 순서로 배치한다. 빈 서식과 작성 목차는 나열하지 않는다.
'''
