"""Review regressions against product modules; no live DB/model dependencies."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.api.tests.test_copilot_v31 import bundle, scope, draft, FakeGateway, ReplayTools
from apps.api.app.copilot.answer_validation import verify, compose
from apps.api.app.copilot.v31_contracts import AnswerEnvelope, Claim, ConversationState, Draft, Task, TaskPlan
from apps.api.app.copilot.conversation_state import ConversationRepository
from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.orchestration import coordinate
from apps.api.app.copilot.tool_adapters import ProductTools


def verdicts(body):
    return {'verdicts': [{'claim_id': c['claim_id'], 'status': 'SUPPORTED', 'reason': 'fixture'} for c in body['claims']]}


def test_duplicate_id_cannot_inherit_semantic_verdict():
    good = draft().claims[0]
    bad = good.model_copy(update={'text': '병원 실적도 인정됩니다.'})
    gateway = FakeGateway({'validate': verdicts})
    claims, _ = verify(Draft(claims=[good, bad]), bundle(), gateway)
    assert all(c.validation != 'SUPPORTED' for c in claims)
    assert not gateway.calls  # ambiguous IDs never reach semantic validation


def test_final_envelope_rejects_duplicate_ids():
    c = Claim(**draft().claims[0].model_dump(), validation='SUPPORTED')
    with pytest.raises(ValidationError):
        AnswerEnvelope(conversation_id=uuid4(), context_revision=1, message_id='m', claims=[c, c])


def test_duplicate_repair_cannot_replace_supported_sibling():
    good = draft().claims[0].model_copy(update={'claim_id': 'good'})
    bad = draft('병원 인정').claims[0].model_copy(update={'claim_id': 'bad'})
    gateway = FakeGateway({'generate': Draft(claims=[good, bad]), 'validate': {'verdicts': [
        {'claim_id': 'good', 'status': 'SUPPORTED', 'reason': 'fixture'},
        {'claim_id': 'bad', 'status': 'CONTRADICTED', 'reason': 'fixture'}]},
        'repair': Draft(claims=[bad, bad.model_copy(update={'text': '검증 우회 문장'})]), 'revalidate': verdicts})
    claims, partial, events = compose(bundle(), TaskPlan(goal='실적', tasks=[Task(kind='READ_DOCUMENT', question='실적')]),
        ConversationState(conversation_id=uuid4(), owner='u', scope=scope()), gateway)
    assert partial and any(c.claim_id == 'good' for c in claims)
    assert not any(c.text == '검증 우회 문장' for c in claims)
    assert not any(c['stage'] == 'revalidate' for c in gateway.calls)
    assert any(e.get('reason') == 'DUPLICATE_REPAIR_CLAIM' for e in events)


def test_mechanical_failure_never_promoted_with_valid_sibling():
    valid = draft().claims[0]
    invalid = valid.model_copy(update={'claim_id': 'bad', 'source_ids': ['missing']})
    claims, _ = verify(Draft(claims=[valid, invalid]), bundle(), FakeGateway({'validate': verdicts}))
    assert claims[0].validation == 'SUPPORTED'
    assert claims[1].validation == 'INSUFFICIENT' and claims[1].reason == 'INVALID_REFERENCE'


def test_evidence_quote_and_scope_serialized_once():
    from apps.api.app.copilot.evidence_payload import evidence_payload
    import json
    b = bundle()
    payload = evidence_payload(b)
    text = json.dumps(payload, ensure_ascii=False)
    assert text.count(b.sources[1].quote) == 1
    assert len(payload['scopes']) == 1
    assert all(f['scope_ref'] == 'current' for f in payload['facts'])


def test_repair_receives_goal_and_supported_siblings():
    good = draft().claims[0].model_copy(update={'claim_id': 'good'})
    bad = draft('병원 인정').claims[0].model_copy(update={'claim_id': 'bad'})
    def repair(body):
        assert body['goal'] == '실적과 예외를 설명'
        assert body['supported_siblings'][0]['claim_id'] == 'good'
        return Draft(claims=[bad.model_copy(update={'text': '병원 제외'})])
    gateway = FakeGateway({'generate': Draft(claims=[good, bad]), 'validate': {'verdicts': [
        {'claim_id': 'good', 'status': 'SUPPORTED', 'reason': 'fixture'},
        {'claim_id': 'bad', 'status': 'CONTRADICTED', 'reason': 'fixture'}]}, 'repair': repair, 'revalidate': verdicts})
    claims, partial, events = compose(bundle(), TaskPlan(goal='실적과 예외를 설명', tasks=[Task(kind='READ_DOCUMENT', question='실적')]),
                                     ConversationState(conversation_id=uuid4(), owner='u', scope=scope()), gateway)
    assert not any(e.get('stage') == 'repair' and e.get('reason') == 'AssertionError' for e in events)
    assert any(c.claim_id == 'bad' and c.text == '병원 제외' for c in claims)


@pytest.mark.parametrize('kind', ['READ_CHECKS', 'READ_PROFILE'])
def test_followup_rereads_origin_adapter(monkeypatch, kind):
    from apps.api.tests.test_copilot_required_checks_narration import _fixture
    summary, checks, profile, _ = _fixture(with_question=True)
    for name, value in [('get_qualification_summary', summary), ('get_required_checks', checks), ('get_judgment_profile_snapshot', profile)]:
        monkeypatch.setattr('apps.api.app.copilot.product_tools.' + name, lambda *a, v=value: v)
    p = summary.provenance
    case = SimpleNamespace(id=p.case_id, company_id=p.company_id, notice_id=p.notice_id, current_version_id=p.notice_version_id)
    db = SimpleNamespace(refresh=lambda *a: None)
    repo = ConversationRepository()
    plan = TaskPlan(goal='조회', tasks=[Task(kind=kind, question='조회')])
    first, _ = coordinate(CopilotChatRequest(case_id=case.id, message='조회'), 'u', ProductTools(db, case),
                          repository=repo, gateway=FakeGateway({'plan': plan}))
    target = next(t for t in first.follow_up_targets if t.kind != 'MANUAL')
    # A wrong re-read is an explicit test failure, rather than fabricating a replacement.
    monkeypatch.setattr(ProductTools, 'judgment', lambda *a: pytest.fail('wrong judgment adapter'))
    monkeypatch.setattr(ProductTools, 'documents', lambda *a: pytest.fail('wrong document adapter'))
    second, _ = coordinate(CopilotChatRequest(case_id=case.id, message='이 항목의 근거', target_id=target.target_id,
        conversation_id=first.conversation_id, context_revision=first.context_revision), 'u', ProductTools(db, case),
        repository=repo, gateway=FakeGateway({'plan': plan}))
    assert second.clarification is None and second.claims
    assert second.processing.tools[0]['tool'] == kind


def test_point_question_limits_topics_but_full_request_preserves_source_scope():
    from apps.api.tests.test_document_rag_store import _record
    from apps.api.tests.test_copilot_v31_readiness import version
    from apps.api.app.document_rag.readiness import snapshot_sources, Readiness, read_passages
    source = snapshot_sources(version(), dimensions=2)
    texts = ['참가자격: 급식 실적 800식 이상.', '※ 병원 급식 실적은 제외한다.'] + [f'제{i}조 운송: 배송 차량 관리.' for i in range(18)]
    source.records = [_record(source.version_id, str(i), t) for i, t in enumerate(texts)]
    for r in source.records: r.metadata.section_index = 1
    result, _ = read_passages(Readiness(source, 'MISSING'), '급식 실적만', broad=False)
    assert len(result) < 10
    assert any('800식' in r.text for r in result) and any('병원' in r.text for r in result)
    all_records, details = read_passages(Readiness(source, 'MISSING'), '전체 참가자격', broad=True)
    assert all_records == source.records
    assert details['returned_chunks'] == details['source_chunks'] == len(source.records)


def test_full_qualification_request_keeps_region_staff_and_transport_conditions():
    from types import SimpleNamespace
    from apps.api.app.document_rag.readiness import read_passages
    texts = ['1. 참가자격: 등록증을 제출해야 한다.',
             '2. 소재지: 전북특별자치도에 본점을 두어야 한다.',
             '3. 상근 인원: 다섯 명 이상이어야 한다.',
             '4. 운반 조건: 직접 운반할 수 있는 허가와 차량을 갖추어야 한다.']
    records = [SimpleNamespace(text=t, metadata=SimpleNamespace(document_id='doc',
               section_index=0, chunk_id=str(i))) for i, t in enumerate(texts)]
    readiness = SimpleNamespace(source=SimpleNamespace(records=records), index=None)
    for question in ('참가자격 전체', '모든 참가 조건과 예외', '준비해야 할 조건 전체'):
        selected, _ = read_passages(readiness, question, broad=True)
        assert [r.text for r in selected] == texts


def test_planner_paraphrase_cannot_narrow_original_full_source_request():
    class ObservedTools(ReplayTools):
        def execute(self, task):
            assert task.question == '이 문서의 모든 조건과 위탁 예외를 설명해줘'
            super().execute(task)
    plan = TaskPlan(goal='조건', tasks=[Task(kind='READ_DOCUMENT', question='참가자 등록 조건')])
    coordinate(CopilotChatRequest(case_id=scope().case_id, message='이 문서의 모든 조건과 위탁 예외를 설명해줘'),
        'u', ObservedTools(), repository=ConversationRepository(), gateway=FakeGateway({'plan':plan}))


@pytest.mark.parametrize('question,expected', [('전체 참가 조건','PARTIAL'), ('병원 예외','FOUND')])
def test_partial_document_set_cannot_claim_full_scope_found(monkeypatch, tmp_path, question, expected):
    from copy import deepcopy
    from apps.api.tests.test_copilot_v31_readiness import version
    v = version()
    damaged = deepcopy(v.documents[0])
    damaged.id = uuid4()
    damaged.extracted_blocks = [{'text':'손상된 \ufffd 원문'}]
    v.documents.append(damaged)
    monkeypatch.setattr('apps.api.app.copilot.tool_adapters.load_notice_version_for_rag',lambda *a:v)
    monkeypatch.setenv('DOCUMENT_RAG_INDEX_ROOT',str(tmp_path))
    case = SimpleNamespace(id=scope().case_id, company_id=scope().company_id, notice_id=v.notice_id,current_version_id=v.id)
    adapter = ProductTools(None,case,allow_documents=True,gateway=SimpleNamespace(available=False))
    adapter.documents(question)
    assert adapter.bundle.facts
    assert adapter.bundle.coverage['READ_DOCUMENT'] == expected


def test_large_fallback_is_bounded_and_explicitly_incomplete():
    b = bundle()
    b.sources[1].quote = '실적은 800식 이상이어야 한다. 병원 실적은 제외한다.\n' * 300
    b.facts[1].text = b.sources[1].quote
    claims, partial, events = compose(b, TaskPlan(goal='실적', tasks=[Task(kind='READ_DOCUMENT', question='실적')]),
                                      ConversationState(conversation_id=uuid4(), owner='u', scope=scope()), FakeGateway())
    assert partial and sum(len(c.text) for c in claims) <= 6000
    assert any(e.get('reason') == 'FALLBACK_BUDGET' for e in events)
    assert b.limitations


def test_request_complete_can_omit_unrelated_facts_and_keep_caveat():
    class ExtraTools(ReplayTools):
        def execute(self, task):
            super().execute(task)
            self.bundle.facts.append(bundle().facts[0])
            self.bundle.sources.append(bundle().sources[0])
            self.bundle.limitations.append('판정 기준일 이후 상황은 별도 확인하세요.')
    plan = TaskPlan(goal='병원 실적 예외', tasks=[Task(kind='READ_DOCUMENT', question='병원 실적 예외')])
    gateway = FakeGateway({'plan': plan, 'generate': draft(), 'validate': verdicts})
    result, _ = coordinate(CopilotChatRequest(case_id=scope().case_id, message=plan.goal), 'u', ExtraTools(),
                           repository=ConversationRepository(), gateway=gateway)
    assert result.processing.task_status == 'PASS'
    assert result.limitations and len(result.claims) == 1
