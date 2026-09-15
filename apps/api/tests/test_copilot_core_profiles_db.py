"""Observe Core J01-J12 against real sources; draft Golden labels are not truth."""
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
import zipfile
import pytest
from sqlalchemy.orm import Session
from apps.api.tests.test_copilot_core_jobs_db import CASES
from apps.api.tests.test_copilot_namwon_snapshot_db import persist_snapshot


@pytest.mark.parametrize('notice_no,first_profile,before,after', CASES)
def test_core_four_profiles_and_two_versions(seed_required_master_codes, notice_no, first_profile, before, after):
    from apps.api.app.database import engine
    from apps.api.app.models import PreflightCase
    from apps.api.app.scripts.seed_golden_v02_accounts import _replace_company_profile
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.copilot.product_tools import get_qualification_summary, get_required_checks
    from apps.api.app.qualification.analysis import analysis_run_response
    from apps.api.app.qualification.rules.requirement_diff import diff_requirements
    root = Path(os.environ['COPILOT_CORE_SNAPSHOTS'])
    data = json.loads((root / (notice_no + '.json')).read_text(encoding='utf-8'))
    with zipfile.ZipFile(os.environ['COPILOT_CORE_PROFILES']) as archive:
        cases = json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('/fixture_bundle.json'))))['cases']
    start = int(first_profile[1:])
    selected = [c for c in cases if c['case_id'] in {f'J{i:02}' for i in range(start, start + 4)}]
    assert len(selected) == 4
    report = {'notice_no': notice_no, 'orders': [before, after], 'results': [],
              'scope': 'local PostgreSQL real product rules, synthetic profiles, rollback; draft expected statuses not acceptance truth'}
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode='create_savepoint')
        try:
            objects = persist_snapshot(db, data)
            versions = {v.bid_notice_order: v for v in objects['BidNoticeVersion']}
            analyses = {a.notice_version_id: a for a in objects['QualificationAnalysisRun']}
            baseline, current = (analyses[versions[order].id] for order in (before, after))
            from apps.api.app.copilot.source_changes import compare_sources
            fingerprint, observations, limitations = compare_sources(versions[before], versions[after])
            report['literal_source_comparison'] = {'fingerprint': fingerprint, 'observations': observations, 'limitations': limitations}
            assert not limitations
            if notice_no == 'R26BK01687120':
                assert '동일 4건, 상이 0건' in observations[0]
                assert any('N → Y' in text for text in observations)
            if notice_no == 'R26BK01634263':
                assert any('1257' in text and '1143' in text for text in observations)
            if notice_no == 'R26BK01633750':
                assert any('2026.07.27' in text for text in observations)
            report['stored_analysis_diff'] = [c.model_dump(mode='json') for c in diff_requirements(
                analysis_run_response(baseline).requirements, analysis_run_response(current).requirements)]
            for profile in selected:
                company = _replace_company_profile(db, profile)
                case = PreflightCase(notice_id=versions[before].notice_id, company_id=company.id,
                    baseline_version_id=versions[before].id, current_version_id=versions[after].id,
                    title=profile['case_id'] + ' Core local source review')
                db.add(case)
                db.flush()
                row = {'profile_id': profile['case_id'], 'versions': []}
                for analysis in (baseline, current):
                    run = run_targeted_qualification_judgment(db, case_id=case.id, analysis_run_id=analysis.id,
                        reference_date=date.fromisoformat(profile['reference_date']))
                    assert run.company_id == company.id and run.notice_version_id == analysis.notice_version_id
                    row['versions'].append({'analysis_status': run.analysis_status, 'status': run.overall_status,
                        'counts': dict(Counter(j.status for j in run.judgments)),
                        'requirements': [{'key': j.requirement_key, 'status': j.status, 'reason': j.reason_code} for j in run.judgments]})
                summary = get_qualification_summary(db, case.id)
                assert summary.provenance.judgment_run_id == run.id
                checks = get_required_checks(db, case.id)
                row['checks'] = checks.model_dump(mode='json')
                report['results'].append(row)
            assert len(report['results']) == 4
        finally:
            Path(os.environ['COPILOT_DB_EVIDENCE'], notice_no + '-profiles.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            db.close()
            transaction.rollback()
