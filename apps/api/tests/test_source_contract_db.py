"""Authenticated product API for source-bound confirmations, not model verdicts."""
import json
from sqlalchemy import select, func
from apps.api.tests.test_copilot_v31_db import state, authenticated_api
from apps.api.tests.test_source_condition_contracts import RAW


def test_structured_confirmation_rejects_truck_only_wrong_basis_and_replay(state, authenticated_api):
    from apps.api.app.analysis_models import QualificationRequirementRecord
    from apps.api.app.judgment_models import QualificationJudgmentRun
    from apps.api.app.qualification.rules.source_contracts import transport_contract
    db, case, analysis, _ = state
    requirement = db.scalar(select(QualificationRequirementRecord).where(QualificationRequirementRecord.analysis_run_id == analysis.id,
        QualificationRequirementRecord.requirement_key == 'REQ-REGISTRATION'))
    requirement.type = 'INDUSTRY'
    requirement.value_json = '1227'
    requirement.raw = RAW
    requirement.scope = {'source_contract': transport_contract(RAW)}
    requirement.condition_complexity = 'composite'
    for evidence in analysis.evidence:
        if evidence.evidence_key in requirement.evidence_keys:
            evidence.quote = RAW
    db.commit()
    prefix = f'/api/v1/preflight-cases/{case.id}'
    source = authenticated_api.post(prefix + '/qualification-judgments', json={'analysis_run_id': str(analysis.id)}).json()
    assert next(j['status'] for j in source['judgments'] if j['requirement_key'] == requirement.requirement_key) == 'UNKNOWN'
    before = db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(QualificationJudgmentRun.preflight_case_id == case.id))
    payload = {'source_judgment_run_id': source['id'], 'requirement_key': requirement.requirement_key,
               'satisfies_requirement': True, 'evidence_held': False}
    answers = {'disposal_permit': True, 'legal_transport_permission': True, 'required_equipment': True}
    for value in [None, '트럭이 있습니다', json.dumps({'basis': 'wrong-version', 'answers': answers}),
                  json.dumps({'basis': transport_contract(RAW)['raw_sha256'], 'answers': {'required_equipment': True}})]:
        response = authenticated_api.post(prefix + '/qualification-answers', json={**payload, 'normalized_value': value})
        assert response.status_code == 422, response.text
        assert response.json()['error']['code'] == 'STRUCTURED_CONFIRMATION_REQUIRED'
    assert db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(QualificationJudgmentRun.preflight_case_id == case.id)) == before
    valid = {**payload, 'normalized_value': json.dumps({'basis': transport_contract(RAW)['raw_sha256'], 'answers': answers})}
    response = authenticated_api.post(prefix + '/qualification-answers', json=valid)
    assert response.status_code == 200, response.text
    result = response.json()['result']
    judgment = next(j for j in result['judgments'] if j['requirement_key'] == requirement.requirement_key)
    assert judgment['status'] == 'SATISFIED' and judgment['value_source'] == 'askback' and not judgment['evidence_held']
    assert result['profile_snapshot'] == source['profile_snapshot']
    assert authenticated_api.post(prefix + '/qualification-answers', json=valid).status_code == 409
