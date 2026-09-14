"""Actual persisted product reads through v3.1; no external model calls."""
from apps.api.tests.test_copilot_product_tools import state
from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.conversation_state import ConversationRepository
from apps.api.app.copilot.model_gateway import ModelGateway
from apps.api.app.copilot.orchestration import coordinate
from apps.api.app.copilot.tool_adapters import ProductTools
import pytest
from apps.api.app.copilot.v31_contracts import Task, TaskPlan
from apps.api.tests.test_copilot_v31 import FakeGateway


def test_v31_reads_real_persisted_judgment_without_external_model(state):
    db, case, analysis, run = state
    gateway = ModelGateway()
    gateway.enabled = False
    envelope, tools = coordinate(CopilotChatRequest(case_id=case.id, message='현재 판정과 회사정보를 알려줘', response_version='3.1'),
                                 'isolated-db-test-user', ProductTools(db, case),
                                 repository=ConversationRepository(), gateway=gateway)
    assert envelope.status_card.status == run.overall_status
    assert envelope.status_card.provenance.analysis_run_id == analysis.id
    assert envelope.status_card.provenance.judgment_run_id == run.id
    assert envelope.claims and envelope.sources
    assert all(s.scope.case_id == case.id and s.scope.notice_version_id == case.current_version_id for s in envelope.sources)
    assert all(c.validation == 'SUPPORTED' and c.method in {'rule', 'extractive'} for c in envelope.claims)
    assert not envelope.actions and not gateway.calls
    assert envelope.processing.task_status == 'PARTIAL'  # extractive is not model task completion
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize('kind', ['READ_CHECKS', 'READ_PROFILE'])
def test_v31_selected_target_rereads_same_persisted_entity(state, kind):
    db, case, _, _ = state
    repo = ConversationRepository()
    plan = TaskPlan(goal='조회', tasks=[Task(kind=kind, question='조회')])
    first, _ = coordinate(CopilotChatRequest(case_id=case.id, message='조회'), 'db-user', ProductTools(db, case),
                          repository=repo, gateway=FakeGateway({'plan': plan}))
    target = first.follow_up_targets[0]
    assert target.origin_tool == kind and target.entity_ref
    second, _ = coordinate(CopilotChatRequest(case_id=case.id, message='항목 근거', target_id=target.target_id,
        conversation_id=first.conversation_id, context_revision=first.context_revision), 'db-user', ProductTools(db, case),
        repository=repo, gateway=FakeGateway({'plan': plan}))
    assert second.clarification is None and second.claims
    assert second.processing.tools[0]['tool'] == kind
    assert {f for c in second.claims for f in c.fact_ids} == set(target.fact_ids)


@pytest.fixture
def authenticated_api(state):
    """Real session cookie + DB dependencies; no authentication overrides."""
    import secrets
    from fastapi.testclient import TestClient
    from apps.api.app.auth import hash_password
    from apps.api.app.auth_models import AppUser
    from apps.api.app.main import app
    db, case, _, _ = state
    password = secrets.token_hex(20)
    user = AppUser(username='copilot-test-' + secrets.token_hex(8), password_hash=hash_password(password),
                   company_id=case.company_id, role='USER', active=True)
    db.add(user)
    db.commit()
    try:
        with TestClient(app) as client:
            response = client.post('/api/v1/auth/login', json={'username': user.username, 'password': password})
            assert response.status_code == 200
            assert client.get('/api/v1/auth/me').json()['company_id'] == str(case.company_id)
            client.test_credentials = {'username': user.username, 'password': password}
            yield client
    finally:
        db.rollback()
        db.delete(user)
        db.commit()


def test_v31_real_login_api_database_and_foreign_company_boundary(state, authenticated_api):
    from apps.api.app.models import Company
    db, case, _, _ = state
    response = authenticated_api.post('/api/v1/copilot/chat', json={
        'case_id': str(case.id), 'message': '현재 판정', 'response_version': '3.1'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['envelope']['claims'] and not payload['external_processing_used']
    foreign = Company(name='isolated-foreign-company', company_size='SMALL')
    db.add(foreign)
    db.flush()
    original = case.company_id
    case.company_id = foreign.id
    db.commit()
    try:
        denied = authenticated_api.post('/api/v1/copilot/chat', json={
            'case_id': str(case.id), 'message': '현재 판정', 'response_version': '3.1'})
        assert denied.status_code == 403
    finally:
        case.company_id = original
        db.delete(foreign)
        db.commit()


def test_structured_proposal_and_ack_use_server_procedure_without_writes(state, authenticated_api):
    from sqlalchemy import func, select
    from apps.api.app.database import SessionLocal
    from apps.api.app.judgment_models import QualificationJudgmentRun
    from apps.api.app.ask_back_models import QualificationAnswer
    _, case, _, _ = state

    def counts():
        with SessionLocal() as observer:
            return tuple(observer.scalar(select(func.count()).select_from(model).where(model.preflight_case_id == case.id))
                         for model in (QualificationJudgmentRun, QualificationAnswer))

    before = counts()
    response = authenticated_api.post('/api/v1/copilot/chat', json={
        'case_id': str(case.id), 'message': '이 등록 항목에 반영해줘', 'response_version': '3.1',
        'requirement_key': 'REQ-REGISTRATION', 'user_input': {'satisfies_requirement': True, 'evidence_held': True}})
    assert response.status_code == 200
    envelope = response.json()['envelope']
    assert len(envelope['actions']) == 1 and counts() == before
    criteria = next(e['criteria'] for e in envelope['processing']['validation_events'] if e['stage'] == 'acceptance')
    assert next(c for c in criteria if c['task_kind'] == 'PROPOSE_ACTION')['fact_ids']
    assert len([c for c in criteria if c['task_kind'] == 'READ_CHECKS']) == 1
    assert all(t['origin_tool'] != 'PROPOSE_ACTION' for t in envelope['follow_up_targets'])
    response = authenticated_api.post('/api/v1/copilot/chat', json={
        'case_id': str(case.id), 'message': '응', 'response_version': '3.1',
        'conversation_id': envelope['conversation_id'], 'context_revision': envelope['context_revision']})
    assert response.status_code == 200
    ack = response.json()['envelope']
    assert ack['processing']['task_status'] == 'PASS' and not ack['processing']['calls']
    assert not ack['actions'] and counts() == before
    assert '명시적으로 실행을 확인' in ack['claims'][0]['text']
    assert [t['tool'] for t in ack['processing']['tools']] == ['ACKNOWLEDGE_ACTION']


def test_natural_ordinal_reference_keeps_subject_and_company_comparison(state):
    db, case, _, _ = state
    repo = ConversationRepository()
    first_plan = TaskPlan(goal='저장 요건 목록', tasks=[Task(kind='READ_JUDGMENT', question='목록')])
    first, _ = coordinate(CopilotChatRequest(case_id=case.id, message='저장 요건 목록'), 'chain-user',
        ProductTools(db, case), repository=repo, gateway=FakeGateway({'plan': first_plan}))
    expected = next(t for t in first.follow_up_targets if t.kind == 'REQUIREMENT' and t.ordinal == 2)
    previous = first
    for message, comparison in [('두 번째 요건을 설명해줘', False), ('그 요건을 다시 설명해줘', False),
                                ('그 요건을 우리 회사와 비교해줘', True)]:
        kinds = ['READ_JUDGMENT', 'READ_PROFILE'] if comparison else ['READ_DOCUMENT']
        plan = TaskPlan(goal=message, tasks=[Task(kind=k, question=message) for k in kinds])
        adapter = ProductTools(db, case)
        result, _ = coordinate(CopilotChatRequest(case_id=case.id, message=message,
            conversation_id=previous.conversation_id, context_revision=previous.context_revision), 'chain-user',
            adapter, repository=repo, gateway=FakeGateway({'plan': plan}))
        assert result.clarification is None
        selected = [f for f in adapter.bundle.facts if f.origin_tool == 'READ_JUDGMENT']
        assert len(selected) == 1 and selected[0].requirement_key == expected.requirement_key
        assert any(f.origin_tool == 'READ_PROFILE' for f in adapter.bundle.facts) is comparison
        previous = result
