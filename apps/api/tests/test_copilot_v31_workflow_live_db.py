"""Persisted write boundaries during actual model-assisted v3.1 conversation."""
import json
import os
from pathlib import Path
from sqlalchemy import func, select

from apps.api.tests.test_copilot_v31_db import state, authenticated_api
from apps.api.tests.test_copilot_v31_browser_live_db import live_model
from apps.api.app.database import SessionLocal
from apps.api.app.judgment_models import QualificationJudgmentRun
from apps.api.app.ask_back_models import QualificationAnswer


def test_changes_assumption_proposal_and_explicit_confirmation(state, authenticated_api, live_model):
    db, case, _, original = state
    from datetime import date
    from apps.api.app.qualification.judgment import run_qualification_judgment
    # A changed-notice comparison requires a persisted baseline judgment too.
    current_version = case.current_version_id
    try:
        case.current_version_id = case.baseline_version_id
        db.commit()
        run_qualification_judgment(db, case_id=case.id, reference_date=date(2026, 9, 8))
    finally:
        case.current_version_id = current_version
        db.commit()
    output = Path(os.environ['COPILOT_DB_EVIDENCE']) / 'workflow-results.json'
    rows, failures = [], []
    envelope = None

    def counts():
        with SessionLocal() as observer:
            return [observer.scalar(select(func.count()).select_from(model).where(model.preflight_case_id == case.id))
                    for model in (QualificationJudgmentRun, QualificationAnswer)]

    def check(condition, label):
        if not condition: failures.append(label)

    def ask(message, **extra):
        nonlocal envelope
        response = authenticated_api.post('/api/v1/copilot/chat', headers={'X-Copilot-Semantic-Processing': 'true'}, json={
            'case_id': str(case.id), 'message': message, 'response_version': '3.1',
            'conversation_id': envelope['conversation_id'] if envelope else None,
            'context_revision': envelope['context_revision'] if envelope else None, **extra})
        rows.append({'message': message, 'http_status': response.status_code, 'body': response.json(), 'counts': counts()})
        assert response.status_code == 200, response.text
        envelope = response.json()['envelope']
        return envelope

    before = counts()
    try:
        change = ask('저장된 변경 요건에서 실적 금액 조건의 이전 값과 현재 값을 비교해줘.')
        check(any(t['tool'] == 'READ_CHANGES' for t in change['processing']['tools']), 'change-tool')
        versions = {s['scope']['notice_version_id'] for s in change['sources']}
        check(str(case.current_version_id) in versions and str(case.baseline_version_id) in versions, 'change-both-versions')
        check(not change['actions'] and counts() == before, 'change-no-write')
        check(change['processing']['task_status'] == 'PASS', 'change-quality')

        assumption = ask('정보통신공사업 등록을 보유하고 있다고 가정하고 해당 조건만 검토해줘.')
        check(any(t['tool'] == 'REVIEW_ASSUMPTION' for t in assumption['processing']['tools']), 'assumption-tool')
        check(not assumption['actions'] and counts() == before, 'assumption-no-write')
        check(any('가정' in x for x in assumption['limitations']), 'assumption-labeled')
        check(assumption['processing']['task_status'] == 'PASS', 'assumption-quality')

        proposal = ask('이 등록 항목에 반영해줘', requirement_key='REQ-REGISTRATION',
                       user_input={'satisfies_requirement': True, 'evidence_held': True})
        assert len(proposal['actions']) == 1, 'Expected reviewable proposal'
        action = proposal['actions'][0]
        check(counts() == before, 'proposal-no-write')
        check(proposal['processing']['task_status'] == 'PASS', 'proposal-quality')
        acknowledgement = ask('응')
        check(not acknowledgement['actions'] and counts() == before, 'acknowledgement-no-write')
        check(acknowledgement['processing']['task_status'] == 'PASS', 'acknowledgement-quality')
        check(any('명시적으로 실행을 확인' in c['text'] for c in acknowledgement['claims']), 'acknowledgement-confirmation-guidance')

        # Independent negative controls: real assumption/proposal evidence must
        # never establish verified ownership or a completed database write.
        from apps.api.app.copilot import orchestration
        from apps.api.app.copilot.answer_validation import verify
        from apps.api.app.copilot.tool_adapters import ProductTools
        from apps.api.app.copilot.v31_contracts import Draft, DraftClaim, Fact, Source
        control_tools = ProductTools(db, case)
        control_tools.judgment()
        basis = next(f for f in control_tools.bundle.facts if f.requirement_key == 'REQ-REGISTRATION')
        control_tools.bundle.sources.append(Source(source_id='control-assumption-source', kind='TURN',
            quote='정보통신공사업 등록 보유를 가정합니다. 실제 보유를 확인하지 않았습니다.', scope=control_tools.scope))
        assumption_fact = Fact(fact_id='control-assumption', kind='ASSUMPTION',
            text='검토용 등록 보유 가정이며 저장되지 않았습니다.', source_ids=['control-assumption-source'], scope=control_tools.scope)
        control_tools.bundle.facts.append(assumption_fact)
        proposal_fact = orchestration.procedure_fact(control_tools.bundle, 'PROPOSE_ACTION',
            '정보통신공사업 등록 보유=True 답변 제안을 만들었습니다. 명시 확인 전이며 아직 저장하지 않았습니다.')
        candidates = Draft(claims=[
            DraftClaim(claim_id='stored', text='등록 요건의 저장된 판정은 UNKNOWN입니다.',
                       fact_ids=[basis.fact_id], source_ids=basis.source_ids),
            DraftClaim(claim_id='false-ownership', text='회사의 실제 정보통신공사업 등록 보유가 검증됐습니다.',
                       fact_ids=[assumption_fact.fact_id, basis.fact_id], source_ids=[*assumption_fact.source_ids, *basis.source_ids]),
            DraftClaim(claim_id='pending', text='등록 보유 답변 제안은 명시 확인 전이며 아직 저장하지 않았습니다.',
                       fact_ids=[proposal_fact.fact_id], source_ids=proposal_fact.source_ids),
            DraftClaim(claim_id='false-saved', text='등록 보유 답변과 새 판정의 저장이 완료됐습니다.',
                       fact_ids=[proposal_fact.fact_id], source_ids=proposal_fact.source_ids),
        ])
        control_claims, control_events = verify(candidates, control_tools.bundle, orchestration.ModelGateway())
        controls = {c.claim_id: c.validation for c in control_claims}
        rows.append({'step': 'semantic-controls', 'claims': [c.model_dump() for c in control_claims], 'events': control_events})
        check(controls.get('stored') == controls.get('pending') == 'SUPPORTED', 'controls-positive')
        check(controls.get('false-ownership') in {'CONTRADICTED', 'INSUFFICIENT'}, 'controls-assumption-not-ownership')
        check(controls.get('false-saved') in {'CONTRADICTED', 'INSUFFICIENT'}, 'controls-proposal-not-saved')
        check(counts() == before, 'controls-no-write')

        response = authenticated_api.post('/api/v1/copilot/actions/confirm', json={'confirmed': False, 'action': action})
        rows.append({'step': 'confirmed-false', 'http_status': response.status_code, 'counts': counts()})
        check(response.status_code == 422 and counts() == before, 'explicit-confirmation-required')

        response = authenticated_api.post('/api/v1/copilot/actions/confirm', json={'confirmed': True, 'action': action})
        rows.append({'step': 'confirmed-true', 'http_status': response.status_code, 'body': response.json(), 'counts': counts()})
        assert response.status_code == 200, response.text
        saved = response.json()
        check(saved['source_judgment_run_id'] == str(original.id), 'source-preserved')
        check(saved['apply_to_profile'] is False, 'profile-not-written')
        check(counts() == [before[0] + 1, before[1] + 1], 'one-answer-one-judgment')
        judgment = next(j for j in saved['result']['judgments'] if j['requirement_key'] == 'REQ-REGISTRATION')
        check(judgment['status'] == 'SATISFIED' and judgment['basis_type'] == 'USER_ANSWER', 'only-confirmed-answer-applied')

        response = authenticated_api.post('/api/v1/copilot/actions/confirm', json={'confirmed': True, 'action': action})
        rows.append({'step': 'replay', 'http_status': response.status_code, 'body': response.json(), 'counts': counts()})
        check(response.status_code == 409 and counts() == [before[0] + 1, before[1] + 1], 'replay-no-write')
    finally:
        output.write_text(json.dumps({'rows': rows, 'failures': failures,
            'scope': 'real login/ASGI/API/DB/model; synthetic fixture; checks completion and write boundaries; acknowledgement is server-authored'},
            ensure_ascii=False, indent=2), encoding='utf-8')
    assert not failures, failures
