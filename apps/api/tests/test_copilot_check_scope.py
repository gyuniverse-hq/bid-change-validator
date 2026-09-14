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
    assert len(manual[0].source_ids) == 2


def test_zero_answer_questions_is_explicit_and_not_all_conditions_satisfied(monkeypatch):
    tools = fixture_tools(monkeypatch,with_question=False)
    tools.required_checks(answerable_only=True)
    assert len(tools.bundle.facts)==1 and tools.bundle.facts[0].entity_ref=='checks_empty'
    assert '모든 참가조건이 충족됐다는 뜻은 아닙니다' in tools.bundle.facts[0].text
    assert tools.bundle.capabilities['answerable_count']==0
