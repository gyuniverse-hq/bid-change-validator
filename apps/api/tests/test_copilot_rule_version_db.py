"""Persisted pre-upgrade judgments must not survive a rule upgrade as fresh results."""
import json
import os
from pathlib import Path

from sqlalchemy import func, select

from apps.api.app.analysis_models import QualificationAnalysisRun, QualificationRequirementRecord
from apps.api.app.database import SessionLocal
from apps.api.app.judgment_models import QualificationJudgmentRun
from apps.api.app.models import Company
from apps.api.app.qualification.judgment import judgment_run_response
from apps.api.app.qualification.rules.judgment import RULE_VERSION
from apps.api.app.revalidation_models import QualificationRevalidationRun
from apps.api.tests.test_copilot_product_tools import state
from apps.api.tests.test_copilot_v31_db import authenticated_api


LEGACY_VERSION = 'qualification-rules-v0.2'


def test_rule_upgrade_blocks_reuse_then_explicit_rejudgment_recovers(state, authenticated_api):
    db, case, current_analysis, _ = state
    api = authenticated_api
    company = db.get(Company, case.company_id)
    company.region_name = '전남광주통합특별시'
    baseline_id = db.scalar(select(QualificationAnalysisRun.id).where(
        QualificationAnalysisRun.notice_version_id == case.baseline_version_id))
    for requirement in db.scalars(select(QualificationRequirementRecord).where(
        QualificationRequirementRecord.analysis_run_id.in_([baseline_id, current_analysis.id]),
        QualificationRequirementRecord.requirement_key == 'REQ-REGION')):
        requirement.value_json = '종전 광주광역시'
        requirement.raw = '종전 광주광역시에 소재한 업체만 참가할 수 있다.'
    db.commit()
    base_url = f'/api/v1/preflight-cases/{case.id}'

    def full_judgment(analysis_id):
        response = api.post(base_url + '/qualification-judgments', json={
            'analysis_run_id': str(analysis_id), 'reference_date': '2026-09-08'})
        assert response.status_code == 200, response.text
        return response.json()

    # Historical persisted fixture, not a claim that the current engine emitted it.
    old_baseline = full_judgment(baseline_id)
    old_current = full_judgment(current_analysis.id)
    old_ids = [old_baseline['id'], old_current['id']]
    db.expire_all()
    old_snapshots = {}
    for run in db.scalars(select(QualificationJudgmentRun).where(QualificationJudgmentRun.id.in_(old_ids))):
        run.rule_version = LEGACY_VERSION
        run.overall_status = 'ineligible'
        for item in run.judgments:
            item.rule_version = LEGACY_VERSION
            if item.requirement_key == 'REQ-REGION':
                item.status = 'UNSATISFIED'
                item.basis_type = 'PROFILE'
                item.reason_code = 'RULE_MISMATCH'
                item.unknown_reason = None
        db.flush()
        old_snapshots[str(run.id)] = judgment_run_response(run).model_dump(mode='json')
    db.commit()

    def counts():
        with SessionLocal() as observer:
            return [observer.scalar(select(func.count()).select_from(model).where(model.preflight_case_id == case.id))
                    for model in (QualificationJudgmentRun, QualificationRevalidationRun)]

    payload = {'source_judgment_run_id': old_baseline['id'],
               'baseline_analysis_run_id': str(baseline_id), 'current_analysis_run_id': str(current_analysis.id),
               'reference_date': '2026-09-08'}
    before = counts()
    rejected = api.post(base_url + '/qualification-revalidation', json=payload)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()['error']['code'] == 'RULE_CHANGED_FULL_REJUDGMENT_REQUIRED'
    assert counts() == before
    proposal = api.post('/api/v1/copilot/chat', json={
        'case_id': str(case.id), 'message': '변경 재검증해줘', 'intent': 'ACTION_REQUEST'})
    assert proposal.status_code == 409, proposal.text
    assert proposal.json()['error']['code'] == 'STALE_ACTION_CONTEXT'
    assert counts() == before

    fresh_baseline = full_judgment(baseline_id)
    fresh_current = full_judgment(current_analysis.id)
    for result in (fresh_baseline, fresh_current):
        assert result['rule_version'] == RULE_VERSION != LEGACY_VERSION
        region = next(j for j in result['judgments'] if j['requirement_key'] == 'REQ-REGION')
        assert region['status'] == 'UNKNOWN' and region['reason_code'] == 'INSUFFICIENT_DATA'
        assert all(j['rule_version'] == RULE_VERSION for j in result['judgments'])
    assert counts() == [before[0] + 2, before[1]]
    accepted = api.post(base_url + '/qualification-revalidation', json={
        **payload, 'source_judgment_run_id': fresh_baseline['id']})
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert 'REQ-REGION' not in result['revalidated_keys']
    assert next(c for c in result['changes'] if c['current_key'] == 'REQ-REGION')['change_type'] == 'UNCHANGED'
    assert next(j for j in result['result']['judgments'] if j['requirement_key'] == 'REQ-REGION')['status'] == 'UNKNOWN'
    assert result['result']['rule_version'] == RULE_VERSION
    assert counts() == [before[0] + 3, before[1] + 1]

    summary = api.post('/api/v1/copilot/chat', json={
        'case_id': str(case.id), 'message': '현재 판정', 'intent': 'QUALIFICATION_SUMMARY'})
    assert summary.status_code == 200, summary.text
    provenance = summary.json()['product_state']['provenance']
    assert provenance['rule_version'] == RULE_VERSION
    assert provenance['judgment_run_id'] == result['result']['id']
    db.expire_all()
    for run in db.scalars(select(QualificationJudgmentRun).where(QualificationJudgmentRun.id.in_(old_ids))):
        assert judgment_run_response(run).model_dump(mode='json') == old_snapshots[str(run.id)]
    assert db.get(Company, case.company_id).region_name == '전남광주통합특별시'
    if output := os.environ.get('COPILOT_DB_EVIDENCE'):
        (Path(output) / 'rule-version-recovery.json').write_text(json.dumps({
            'old_version': LEGACY_VERSION, 'current_version': RULE_VERSION,
            'old_region_status': 'UNSATISFIED', 'new_region_status': 'UNKNOWN',
            'rejection': rejected.json(), 'proposal_rejection': proposal.json(),
            'counts_before': before, 'counts_after': counts(), 'historical_snapshots_unchanged': True,
            'new_provenance': provenance, 'revalidated_keys': result['revalidated_keys'],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
