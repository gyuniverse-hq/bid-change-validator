"""User evaluation regression: visit questions must not inherit transport evidence."""
import hashlib
from types import SimpleNamespace
import pytest
from apps.api.app.copilot.acceptance import answerable_checks_request
from apps.api.app.copilot.answer_validation import mechanical
from apps.api.app.copilot.tool_adapters import ProductTools
from apps.api.app.copilot.v31_contracts import Claim, Fact, Source, EvidenceBundle
from apps.api.tests.test_copilot_v31 import scope
from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.qualification.rules.askability import build_semantic_question
from apps.api.app.qualification.rules.source_contracts import VERSION


def test_visit_and_transport_confirmation_wording_are_not_shared():
    raw = '현장 방문 확인서 제출 업체에 한하여 입찰 참가를 인정한다.'
    req = QualificationRequirement(requirement_key='visit',notice_version_id='v2',type='REGISTRATION_CERTIFICATION',
        operator='MATCH',value='현장 방문',raw=raw,condition_complexity='composite',evidence_keys=['v'],
        scope={'source_contract':{'version':VERSION,'kind':'SITE_VISIT','raw_sha256':hashlib.sha256(raw.encode()).hexdigest()}})
    question = build_semantic_question(req)
    assert '현장 방문' in question and '제출' in question
    assert '장비' not in question and '운반' not in question
    from apps.api.tests.test_source_condition_contracts import transport
    assert '법적 운반 자격' in build_semantic_question(transport())


@pytest.mark.parametrize('question,expected',[
    ('추가 답변이 필요한 확인 질문을 알려줘.',True),
    ('답변 입력 가능한 질문만 정리해줘',True),
    ('추가 답변이 필요한 확인 질문과 공고 전체 조건을 알려줘',False),
    ('공고에서 직접 확인할 사항도 모두 알려줘',False),
])
def test_explicit_answer_questions_do_not_absorb_general_notice_review(question,expected):
    assert answerable_checks_request(question) == expected


def test_cross_question_fact_combination_is_rejected_without_model():
    s = scope()
    facts = [Fact(fact_id=k,kind='SERVER_RESULT',text=k,source_ids=[k],scope=s,
                  origin_tool='READ_CHECKS',entity_ref=k) for k in ['visit','transport']]
    b = EvidenceBundle(scope=s,facts=facts,sources=[Source(source_id=k,kind='DOCUMENT',quote=k,scope=s) for k in ['visit','transport']])
    claim = Claim(claim_id='bad',text='운반 허가를 확인하세요.',fact_ids=['visit','transport'],source_ids=['visit','transport'])
    assert mechanical(claim,b) == 'MIXED_CHECK_ENTITIES'
    claim.speech_act='CHECK_REQUEST'
    assert mechanical(claim,b) == 'MIXED_CHECK_ENTITIES'  # Unknown or editable inputs remain separate.
    b.server_context['check_guidance']={k:{'input_allowed':False} for k in ['visit','transport']}
    claim.text='방문 이력과 운반 허가를 각각 원문과 대조해 확인하세요.'
    assert mechanical(claim,b) is None  # Still needs ordinary semantic source validation.
    claim.speech_act='ASSERTION'
    claim.text='준비 순서는 제안입니다. 방문 이력과 운반 허가를 각각 확인한 뒤 제출 자료를 준비하세요.'
    assert mechanical(claim,b) is None  # Read-only sequence advice also needs semantic verification.
    claim.text='방문과 운반 허가는 모두 충족합니다.'
    assert mechanical(claim,b)=='MIXED_CHECK_ENTITIES'
    claim.speech_act='CHECK_REQUEST'
    claim.text='방문 이력과 운반 허가를 각각 원문과 대조해 확인하세요.'
    b.server_context['check_guidance']['transport']['input_allowed']=True
    assert mechanical(claim,b) == 'MIXED_CHECK_ENTITIES'


def fixture_tools(monkeypatch, with_question=True):
    from apps.api.tests.test_copilot_required_checks_narration import _fixture
    summary, checks, _, _ = _fixture(with_question=with_question)
    p = summary.provenance
    manual = summary.analysis_scope.notice_facts[0]
    manual.evidence.append(manual.evidence[0].model_copy(update={'evidence_key':'other','quote':'운반 예외는 별도 검수한다.'}))
    visit = manual.evidence[0].model_copy(update={'evidence_key':'visit','quote':'8월 20~21일 현장 방문 후 확인서를 제출해야 한다.'})
    if checks.questions:
        checks.questions[0].question = '현장 방문과 확인서 제출을 각각 확인해 주세요.'
    monkeypatch.setattr('apps.api.app.copilot.product_tools.get_qualification_summary',lambda *a:summary)
    monkeypatch.setattr('apps.api.app.copilot.product_tools.get_required_checks',lambda *a:checks)
    monkeypatch.setattr('apps.api.app.copilot.product_tools.get_explanation_evidence',lambda db,cid,keys:
        [SimpleNamespace(provenance=p,requirement=SimpleNamespace(requirement_key=k),evidence=[visit]) for k in keys])
    return ProductTools(None,SimpleNamespace(id=p.case_id,company_id=p.company_id,notice_id=p.notice_id,current_version_id=p.notice_version_id))


def test_answer_only_has_one_current_question_and_its_own_document(monkeypatch):
    tools = fixture_tools(monkeypatch)
    tools.required_checks(answerable_only=True)
    assert len(tools.bundle.facts) == 1
    assert tools.bundle.capabilities == {'answerable_count':1,'unanswerable_count':0,'manual_review_count':0}
    assert any('8월 20~21일' in s.quote for s in tools.bundle.sources)
    assert all('운반' not in s.quote for s in tools.bundle.sources)


def test_manual_item_with_two_sources_keeps_one_target_entity(monkeypatch):
    tools = fixture_tools(monkeypatch)
    tools.required_checks()
    manual = [f for f in tools.bundle.facts if f.target_kind=='MANUAL']
    assert len(manual) == tools.bundle.capabilities['manual_review_count'] == 1
    sources = [s for s in tools.bundle.sources if s.source_id in manual[0].source_ids]
    assert sum(s.kind == 'DOCUMENT' for s in sources) == 2
    assert sum(s.kind == 'PRODUCT' for s in sources) == 1
    assert '답변 입력 대상이 아니며' in next(s.quote for s in sources if s.kind == 'PRODUCT')


def test_zero_answer_questions_is_explicit_and_not_all_conditions_satisfied(monkeypatch):
    tools = fixture_tools(monkeypatch,with_question=False)
    tools.required_checks(answerable_only=True)
    assert len(tools.bundle.facts)==1 and tools.bundle.facts[0].entity_ref=='checks_empty'
    assert '모든 참가조건이 충족됐다는 뜻은 아닙니다' in tools.bundle.facts[0].text
    assert tools.bundle.capabilities['answerable_count']==0
def test_manual_input_capability_cannot_be_overridden_by_model():
    from apps.api.tests.test_copilot_v31 import bundle,draft
    from apps.api.app.copilot.answer_validation import mechanical
    from apps.api.app.copilot.v31_contracts import Claim
    b=bundle()
    b.server_context['check_guidance']={'exception':{'input_allowed':False,'text':'원문을 확인하세요. 앱의 답변 입력 대상이 아닙니다.'}}
    c=Claim(**draft('확인 결과는 지금 입력할 수 있습니다.').claims[0].model_dump())
    assert mechanical(c,b)=='INPUT_CAPABILITY_MISMATCH'
    c.text='이 항목은 앱의 답변 입력 대상이 아닙니다.'
    assert mechanical(c,b) is None
    c.text='이 항목은 앱에 답변을 저장하는 대상이 아니므로 원문을 확인해 주세요.'
    assert mechanical(c,b) is None
    c.text+=' 하지만 지금 답변을 저장하세요.'
    assert mechanical(c,b)=='INPUT_CAPABILITY_MISMATCH'
    c.text='국가계약법상 자격은 앱에 답변을 입력하거나 저장된 회사정보만으로 확인할 수 없는 항목입니다. 직접 점검해야 합니다.'
    assert mechanical(c,b) is None
    c.text+=' 이곳에 답변을 입력하시면 됩니다.'
    assert mechanical(c,b)=='INPUT_CAPABILITY_MISMATCH'
    c.text='이 조건은 앱 입력으로 확인되지 않으므로 업체 기록을 확인해 주세요.'
    # Absence of a mechanical error never bypasses semantic verification.
    from apps.api.app.copilot.answer_validation import verify
    from apps.api.tests.test_copilot_v31 import FakeGateway
    from apps.api.app.copilot.v31_contracts import Draft, DraftClaim, Verdicts
    checked,_=verify(Draft(claims=[DraftClaim(**c.model_dump(exclude={'validation','method','reason'}))]),b,
        FakeGateway({'validate':Verdicts(verdicts=[dict(claim_id=c.claim_id,status='CONTRADICTED',reason='manual item is not writable')])}))
    assert checked[0].validation=='CONTRADICTED'


def test_manual_guidance_keeps_original_exception_and_actual_input_mode():
    from apps.api.tests.test_copilot_v31 import bundle,draft
    from apps.api.app.copilot.check_guidance import controlled_checks
    from apps.api.app.copilot.acceptance import AcceptanceCriterion
    b=bundle();b.facts[1].origin_tool='READ_CHECKS'
    fid=b.facts[1].fact_id
    text='병원 실적은 제외됩니다. 이 원문 조건을 확인하세요. 앱의 답변 입력 대상이 아닙니다.'
    b.server_context['check_guidance']={fid:{'input_allowed':False,'text':text}}
    criterion=AcceptanceCriterion(criterion_id='READ_CHECKS:0',task_kind='READ_CHECKS',mode='CHECKLIST',requirement='확인할 일',fact_ids=(fid,))
    fixed=controlled_checks(draft('병원 실적도 입력하면 됩니다.',fid),b,[criterion])
    assert len(fixed.claims)==1 and fixed.claims[0].text==text
    assert fixed.claims[0].source_ids==b.facts[1].source_ids


def test_overall_judgment_cannot_be_assigned_to_a_manual_document_condition():
    from apps.api.tests.test_copilot_v31 import bundle,draft
    from apps.api.app.copilot.answer_validation import mechanical
    from apps.api.app.copilot.v31_contracts import Claim
    b=bundle();b.facts[1].origin_tool='READ_DOCUMENT';b.facts[1].target_kind='MANUAL'
    c=Claim(**draft('이 등록 요건에 대한 저장 종합 판정은 미달로 남아 있습니다.').claims[0].model_dump())
    assert mechanical(c,b)=='UNBOUND_REQUIREMENT_JUDGMENT'
    c.text='이 등록 요건의 실제 충족 여부는 직접 확인해야 합니다.'
    assert mechanical(c,b) is None
    c.text='현재 저장된 전체 판정은 참가 불가입니다. 이 등록 조건은 원문에서 확인해야 합니다.'
    assert mechanical(c,b) is None


def test_judgment_reason_preserves_declared_answer_and_group_relation(monkeypatch):
    tools=fixture_tools(monkeypatch)
    summary=tools._summary()
    item=summary.judgments[0].model_copy(update={
        'basis_type':'USER_ANSWER','value_source':'askback','evidence_status':'declared',
        'evaluated_condition':{'source_group':{'relation':'AND','review_scope':'LOCAL_GOLDEN_V03_ONLY'},
                               'source_contract':{'kind':'WASTE_TRANSPORT'}}})
    basis=tools._judgment_basis(item)
    assert basis['value_source']=='askback' and '실제 증빙 검증이 아님' in basis['meaning']
    assert basis['condition']['source_group']['relation']=='AND'
    assert basis['condition']['source_contract']['kind']=='WASTE_TRANSPORT'


def test_mixed_invalid_input_promise_is_replaced_without_inventing_other_content():
    from apps.api.tests.test_copilot_v31 import bundle,draft
    from apps.api.app.copilot.check_guidance import controlled_checks
    from apps.api.app.copilot.acceptance import AcceptanceCriterion
    b=bundle();b.facts[1].origin_tool='READ_CHECKS';fid=b.facts[1].fact_id
    text='원문 조건을 직접 확인하세요. 앱의 답변 입력 대상이 아닙니다.'
    b.server_context['check_guidance']={fid:{'input_allowed':False,'text':text}}
    d=draft('등록 결과를 입력하면 됩니다.',fid);d.claims[0].fact_ids.append(b.facts[0].fact_id)
    c=AcceptanceCriterion(criterion_id='READ_CHECKS:0',task_kind='READ_CHECKS',mode='CHECKLIST',requirement='확인할 일',fact_ids=(fid,))
    fixed=controlled_checks(d,b,[c])
    assert len(fixed.claims)==1 and fixed.claims[0].text==text
