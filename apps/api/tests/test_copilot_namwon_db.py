"""Observe the unmodified J13-J16 Golden adapter through real PostgreSQL judgment."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID
import zipfile

import pytest
from sqlalchemy.orm import Session


def test_namwon_four_profiles_reach_product_judgment():
    if not os.getenv('COPILOT_NAMWON_BUNDLE') or not os.getenv('COPILOT_DB_EVIDENCE'):
        pytest.skip('Guarded local Docker runner and explicit Golden archive required')
    from apps.api.app.database import engine
    from apps.api.app.scripts.seed_golden_v02_accounts import seed_golden_v02_accounts
    from apps.api.app.qualification.judgment import run_qualification_judgment
    from apps.api.app.copilot.product_tools import get_required_checks
    from apps.api.app.models import PreflightCase
    archive = Path(os.environ['COPILOT_NAMWON_BUNDLE'])
    output = Path(os.environ['COPILOT_DB_EVIDENCE'])
    with zipfile.ZipFile(archive) as z:
        bundle_name = next(n for n in z.namelist() if n.endswith('/fixture_bundle.json'))
        evidence_name = next(n for n in z.namelist() if n.endswith('/sources/evidence_all.json'))
        bundle = json.loads(z.read(bundle_name))
        cases = [c for c in bundle['cases'] if c['case_id'] in {'J13', 'J14', 'J15', 'J16'}]
        assert len(cases) == 4 and all(c['notice_no'] == 'R26BK01684863' for c in cases)
        evidence = json.loads(z.read(evidence_name))
    selected = output / 'selected-golden'
    (selected / 'sources').mkdir(parents=True)
    # Preserve every field of the selected cases; do not rewrite held mappings to pass.
    (selected / 'fixture_bundle.json').write_text(json.dumps({'cases': cases}, ensure_ascii=False), encoding='utf-8')
    used = {key for c in cases for entry in c['canonical_inputs'] for key in entry['requirement']['evidence_keys']}
    (selected / 'sources/evidence_all.json').write_text(json.dumps([e for e in evidence if e['evidence_id'] in used], ensure_ascii=False), encoding='utf-8')
    rows, failures = [], []
    # Commit calls in the existing seed/judgment code release SAVEPOINTs only.
    # The containing SQL transaction is always rolled back, preserving prior rows.
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode='create_savepoint')
        try:
            import secrets
            seeded = seed_golden_v02_accounts(db, bundle_dir=selected, password=secrets.token_hex(20),
                                             include_analysis=True, create_missing_notices=True)
            by_id = {c['case_id']: c for c in cases}
            for account in seeded['accounts']:
                source = by_id[account['case_id']]
                case_id = UUID(account['preflight_case_id'])
                run = run_qualification_judgment(db, case_id=case_id, reference_date=date.fromisoformat(source['reference_date']))
                checks = get_required_checks(db, case_id)
                case = db.get(PreflightCase, case_id)
                judgments = [{'key': j.requirement_key, 'status': j.status, 'basis_type': j.basis_type,
                              'reason_code': j.reason_code} for j in run.judgments]
                transport = next(j for j in judgments if j['key'].endswith(':transport_literal'))
                expected = next(a['expected_status'] for a in source['assertions'] if a['key'] == 'transport_literal')
                row = {'case_id': source['case_id'], 'profile_industries': [i['code'] for i in source['profile']['industries']],
                       'scenario_facts': source['scenario_facts'], 'source_review_status': source['review_status'],
                       'expected_transport': expected, 'actual_transport': transport,
                       'overall_status': run.overall_status, 'judgments': judgments,
                       'checks': checks.model_dump(mode='json'),
                       'baseline_equals_current': case.baseline_version_id == case.current_version_id}
                rows.append(row)
                if transport['status'] != expected:
                    failures.append(source['case_id'] + ': transport expected ' + expected + ', observed ' + transport['status'])
        finally:
            db.close()
            outer.rollback()
            output.joinpath('namwon-results.json').write_text(json.dumps({'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'source': archive.name, 'rows': rows, 'failures': failures,
                'scope': 'unmodified selected Golden canonical inputs -> existing seed adapter -> actual PostgreSQL product judgment; no model; outer rollback; not browser E2E',
                'expected_scope': 'Golden transport predicate only; not full-notice eligibility approval'},
                ensure_ascii=False, indent=2), encoding='utf-8')
    assert not failures, failures
