"""Replay approved source snapshots with Golden profiles, without altering the inputs."""
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4
import zipfile

import pytest
from sqlalchemy.orm import Session


def persist_snapshot(db, data):
    from apps.api.app.models import BidNotice, BidNoticeVersion, NoticeDocument
    from apps.api.app.analysis_models import QualificationAnalysisRun, QualificationRequirementRecord, QualificationEvidenceRecord
    collections = [(BidNotice,[data['notice']]),(BidNoticeVersion,data['versions']),
        (NoticeDocument,data['documents']),(QualificationAnalysisRun,data['analyses']),
        (QualificationRequirementRecord,data['requirements']),(QualificationEvidenceRecord,data['evidence'])]
    identities = {row['id']:str(uuid4()) for _,rows in collections for row in rows}
    created = {}
    for model, rows in collections:
        created[model.__name__] = []
        for row in rows:
            values = {}
            for column in model.__table__.columns:
                if column.name not in row: continue
                value = row[column.name]
                if isinstance(value,str) and (column.name=='id' or column.name.endswith('_id')):
                    value = identities.get(value,value)
                # Institution master data is outside this notice-only export.
                if column.name in {'announcing_institution_code','demanding_institution_code'}: value = None
                if value is not None:
                    try: kind = column.type.python_type
                    except NotImplementedError: kind = None
                    if kind is UUID: value = UUID(value)
                    elif kind is datetime: value = datetime.fromisoformat(value)
                    elif kind is date: value = date.fromisoformat(value)
                values[column.name] = value
            if model is BidNotice:
                values['bid_notice_no'] = 'LOCAL-SNAPSHOT-' + uuid4().hex[:12]
            obj = model(**values)
            db.add(obj)
            created[model.__name__].append(obj)
        db.flush()
    return created


def test_latest_namwon_snapshot_with_j13_to_j16(seed_required_master_codes):
    if not os.getenv('COPILOT_NAMWON_SNAPSHOT') or not os.getenv('COPILOT_DB_EVIDENCE'):
        pytest.skip('Guarded local runner and approved snapshot required')
    from apps.api.app.database import engine
    from apps.api.app.models import PreflightCase
    from apps.api.app.scripts.seed_golden_v02_accounts import _replace_company_profile
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.qualification.analysis import analysis_run_response
    from apps.api.app.qualification.rules.requirement_diff import diff_requirements
    from apps.api.app.document_rag.readiness import snapshot_sources
    from apps.api.app.copilot.product_tools import get_required_checks
    snapshot_path = Path(os.environ['COPILOT_NAMWON_SNAPSHOT'])
    data = json.loads(snapshot_path.read_text(encoding='utf-8'))
    assert data['notice_no']=='R26BK01684863'
    with zipfile.ZipFile(os.environ['COPILOT_NAMWON_BUNDLE']) as z:
        cases = json.loads(z.read(next(n for n in z.namelist() if n.endswith('/fixture_bundle.json'))))['cases']
    selected = [c for c in cases if c['case_id'] in {'J13','J14','J15','J16'}]
    assert len(selected)==4
    rows, failures, source_checks = [], [], []
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection,join_transaction_mode='create_savepoint')
        try:
            objects = persist_snapshot(db,data)
            versions = sorted(objects['BidNoticeVersion'],key=lambda v:v.version_number)
            analyses = {a.notice_version_id:a for a in objects['QualificationAnalysisRun']}
            assert [v.version_number for v in versions]==[1,2]
            for version in versions:
                snapshot = snapshot_sources(version)
                source_checks.append({'version':version.version_number,'source_status':snapshot.source_status,
                    'records':len(snapshot.records),'limitations':snapshot.limitations})
            baseline,current = (analyses[v.id] for v in versions)
            changes = [c.model_dump(mode='json') for c in diff_requirements(analysis_run_response(baseline).requirements,analysis_run_response(current).requirements)]
            for source in selected:
                company = _replace_company_profile(db,source)
                case = PreflightCase(notice_id=versions[0].notice_id,company_id=company.id,
                    baseline_version_id=versions[0].id,current_version_id=versions[1].id,title=source['case_id']+' snapshot replay')
                db.add(case)
                db.flush()
                outcomes = []
                for analysis in (baseline,current):
                    run = run_targeted_qualification_judgment(db,case_id=case.id,analysis_run_id=analysis.id,
                        reference_date=date.fromisoformat(source['reference_date']))
                    outcomes.append({'version':1 if analysis is baseline else 2,'overall':run.overall_status,
                        'judgments':[{'key':j.requirement_key,'status':j.status,'reason':j.reason_code} for j in run.judgments]})
                transport = next(j for j in outcomes[-1]['judgments'] if j['key']=='REQ-004-INDUSTRY')
                expected = next(a['expected_status'] for a in source['assertions'] if a['key']=='transport_literal')
                rows.append({'case':source['case_id'],'scenario_facts':source['scenario_facts'],
                    'industries':[i['code'] for i in source['profile']['industries']],
                    'expected_transport':expected,'observed_transport':transport,'versions':outcomes,
                    'required_checks':get_required_checks(db,case.id).model_dump(mode='json')})
                if transport['status']!=expected:
                    failures.append(f"{source['case_id']}: expected {expected}, observed {transport['status']}")
        finally:
            db.close()
            transaction.rollback()
    Path(os.environ['COPILOT_DB_EVIDENCE'],'namwon-snapshot-results.json').write_text(json.dumps({
        'snapshot_sha256':hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        'captured_at':data['captured_at'],'source_checks':source_checks,'changes':changes,'rows':rows,'failures':failures,
        'scope':'approved DB extraction/analysis snapshot, original UUIDs remapped, four draft Golden profiles; product rules on local PG16; rolled back; not original-file or independent legal verification'},
        ensure_ascii=False,indent=2),encoding='utf-8')
    assert not failures, failures
