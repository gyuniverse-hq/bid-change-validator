"""Real browser to isolated API and DB. Only run via the guarded Docker runner."""
import json
import os
from pathlib import Path
import socket
import subprocess
from threading import Thread
import time

import pytest

from apps.api.tests.test_copilot_v31_db import state, authenticated_api


def run_http_browser(state, authenticated_api, script='check-copilot-v31-db-browser.mjs', extra_env=None):
    if not os.getenv('COPILOT_DB_EVIDENCE'):
        pytest.skip('Guarded Docker runner required')
    import uvicorn
    from apps.api.app.main import app
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=18123, log_level='warning'))
    # Reserve this loopback port explicitly; cannot accidentally talk to a prior server.
    sock = socket.socket()
    sock.bind(('127.0.0.1', 18123))
    sock.listen(128)
    thread = Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(0.05)
        assert server.started
        env = os.environ.copy()
        env.update(COPILOT_BROWSER_CREDENTIALS=json.dumps(authenticated_api.test_credentials),
                   COPILOT_BROWSER_CASE=str(state[1].id))
        env.update(extra_env or {})
        result = subprocess.run(['node', 'apps/web/scripts/' + script],
                                env=env, capture_output=True, text=True, encoding='utf-8', timeout=150)
        Path(os.environ['COPILOT_DB_EVIDENCE'], 'browser.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def test_browser_login_chat_selected_target_against_real_db(state, authenticated_api):
    run_http_browser(state, authenticated_api)


def test_browser_source_bound_confirmation(state, authenticated_api):
    from sqlalchemy import select
    from apps.api.app.analysis_models import QualificationRequirementRecord
    from apps.api.tests.test_source_condition_contracts import RAW
    from apps.api.app.qualification.rules.source_contracts import transport_contract
    db, case, analysis, _ = state
    requirement = db.scalar(select(QualificationRequirementRecord).where(QualificationRequirementRecord.analysis_run_id == analysis.id,
        QualificationRequirementRecord.requirement_key == 'REQ-REGISTRATION'))
    requirement.type, requirement.value_json, requirement.raw = 'INDUSTRY', '1227', RAW
    requirement.scope, requirement.condition_complexity = {'source_contract': transport_contract(RAW)}, 'composite'
    for evidence in analysis.evidence:
        if evidence.evidence_key in requirement.evidence_keys:
            evidence.quote = RAW
    db.commit()
    response = authenticated_api.post(f'/api/v1/preflight-cases/{case.id}/qualification-judgments', json={'analysis_run_id': str(analysis.id)})
    assert response.status_code == 200, response.text
    run_http_browser(state, authenticated_api, 'check-source-confirmation-browser.mjs')


def test_browser_account_switch_and_rule_recovery(state, authenticated_api):
    import secrets
    from sqlalchemy import select
    from apps.api.app.auth import hash_password
    from apps.api.app.auth_models import AppUser
    from apps.api.app.models import Company, PreflightCase
    from apps.api.app.analysis_models import QualificationAnalysisRun
    from apps.api.app.judgment_models import QualificationJudgmentRun
    from apps.api.app.qualification.rules.judgment import RULE_VERSION
    db, case, _, _ = state
    baseline = db.scalar(select(QualificationAnalysisRun).where(
        QualificationAnalysisRun.notice_version_id == case.baseline_version_id))
    response = authenticated_api.post(f'/api/v1/preflight-cases/{case.id}/qualification-judgments',
        json={'analysis_run_id': str(baseline.id), 'reference_date': '2026-09-08'})
    assert response.status_code == 200
    db.expire_all()
    historical = []
    for run in db.scalars(select(QualificationJudgmentRun).where(QualificationJudgmentRun.preflight_case_id == case.id)):
        run.rule_version = 'qualification-rules-v0.2'
        historical.append(run.id)
    company = Company(name='Browser isolation second company', company_size='SMALL')
    db.add(company)
    db.flush()
    second_case = PreflightCase(notice_id=case.notice_id, company_id=company.id,
        baseline_version_id=case.baseline_version_id, current_version_id=case.current_version_id, title="Second account test case")
    db.add(second_case)
    password = secrets.token_hex(20)
    user = AppUser(username='browser-second-' + secrets.token_hex(8), password_hash=hash_password(password),
                   company_id=company.id, role='USER', active=True)
    db.add(user)
    db.commit()
    try:
        run_http_browser(state, authenticated_api, 'check-copilot-recovery-db-browser.mjs', {
            'COPILOT_BROWSER_SECOND_CREDENTIALS': json.dumps({'username':user.username,'password':password}),
            'COPILOT_BROWSER_SECOND_COMPANY':str(company.id),
            'COPILOT_BROWSER_SECOND_CASE':str(second_case.id),
            'COPILOT_BROWSER_COMPANY':str(case.company_id),
        })
        db.expire_all()
        runs = list(db.scalars(select(QualificationJudgmentRun).where(QualificationJudgmentRun.preflight_case_id == case.id)))
        assert len(runs) == len(historical) + 3  # baseline/current review, then one changed-scope result
        assert all(r.rule_version == ('qualification-rules-v0.2' if r.id in historical else RULE_VERSION) for r in runs)
    finally:
        db.rollback()
        db.delete(second_case)
        db.delete(user)
        db.flush()
        db.delete(company)
        db.commit()
