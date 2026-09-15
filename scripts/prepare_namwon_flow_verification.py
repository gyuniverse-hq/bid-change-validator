"""Add a separate notice/version/case graph to the owned local evaluation DB.

Original J13, its notice analyses, profile, answers and judgments are read-only.
No resets, model calls, or shared database access.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.local_copilot_evaluation import configure, STATE, save


def protected(db, original):
    from sqlalchemy import select
    from apps.api.app.analysis_models import QualificationAnalysisRun
    from apps.api.app.judgment_models import QualificationJudgmentRun
    from apps.api.app.ask_back_models import QualificationAnswer
    from apps.api.app.models import Company
    from apps.api.app.judgment_models import CompanyQualificationProfileCompleteness
    from apps.api.app.qualification.judgment import build_company_profile_snapshot, _record_to_completeness
    def row(obj):
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    company = db.get(Company, original.company_id)
    completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, company.id))
    value = {'case': row(original), 'profile': build_company_profile_snapshot(company, completeness).model_dump(mode='json'),
        'analyses': [row(x) for x in db.scalars(select(QualificationAnalysisRun).where(
            QualificationAnalysisRun.notice_version_id.in_([original.baseline_version_id, original.current_version_id])).order_by(QualificationAnalysisRun.id))],
        'judgments': [row(x) for x in db.scalars(select(QualificationJudgmentRun).where(
            QualificationJudgmentRun.preflight_case_id == original.id).order_by(QualificationJudgmentRun.id))],
        'answers': [row(x) for x in db.scalars(select(QualificationAnswer).where(
            QualificationAnswer.preflight_case_id == original.id).order_by(QualificationAnswer.id))]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', type=Path)
    args = parser.parse_args()
    identity = configure()
    assert json.loads((STATE / 'manifest.json').read_text(encoding='utf-8'))['database'] == identity
    from sqlalchemy.orm import Session
    from apps.api.app.database import engine
    from apps.api.app.models import PreflightCase, Company
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.tests.test_copilot_namwon_snapshot_db import persist_snapshot
    from apps.api.app.document_rag.readiness import snapshot_sources
    account = next(a for a in json.loads((STATE / 'accounts.private.json').read_text(encoding='utf-8')) if a['username'] == 'eval-j13')
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode='create_savepoint')
        try:
            original = db.get(PreflightCase, UUID(account['case_id']))
            before = protected(db, original)
            if args.check:
                report = json.loads(args.check.read_text(encoding='utf-8'))
                assert report['database'] == identity and report['protected_j13_sha256'] == before
                print('PASS: original J13 case, profile, analyses, answers and judgments unchanged')
                return
            source_path = ROOT / '.ci-results/namwon-source-reextracted.json'
            data = json.loads(source_path.read_text(encoding='utf-8'))
            assert data['notice_no'] == 'R26BK01684863'
            originals = {p.stem: p for p in (STATE / 'documents').iterdir() if p.is_file()}
            assert all(d['file_sha256'] in originals for d in data['documents'])
            objects = persist_snapshot(db, data)
            for doc in objects['NoticeDocument']:
                path = originals[doc.file_sha256]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == doc.file_sha256
                doc.storage_key, doc.download_status = path.name, 'DOWNLOADED'
            versions = sorted(objects['BidNoticeVersion'], key=lambda v: v.version_number)
            assert [v.version_number for v in versions] == [1, 2]
            assert all(v.id not in {original.baseline_version_id, original.current_version_id} for v in versions)
            source_checks = [{'version': v.version_number, 'status': snapshot_sources(v).source_status} for v in versions]
            case = PreflightCase(notice_id=versions[0].notice_id, company_id=original.company_id,
                baseline_version_id=versions[0].id, current_version_id=versions[1].id,
                title='남원 핵심 흐름 검증 전용 [과거 공고·합성 회사·Q-009 보류]')
            db.add(case); db.flush()
            analyses = {a.notice_version_id: a for a in objects['QualificationAnalysisRun']}
            runs = []
            for version in versions:
                result = run_targeted_qualification_judgment(db, case_id=case.id,
                    analysis_run_id=analyses[version.id].id, reference_date=date(2026, 8, 18))
                runs.append({'version': version.version_number, 'judgment_id': str(result.id),
                             'analysis_id': str(result.analysis_run_id), 'status': result.overall_status})
            db.expire_all()
            assert before == protected(db, original)
            folder = STATE / ('namwon-flow-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
            folder.mkdir()
            report = {'database': identity, 'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
                'case_id': str(case.id), 'notice_id': str(case.notice_id), 'original_case_id': account['case_id'],
                'protected_j13_sha256': before, 'runs': runs, 'source_checks': source_checks,
                'account': {**account, 'case_id': str(case.id), 'url': f'http://127.0.0.1:5181/changes?caseId={case.id}'}}
            save(folder / 'setup.private.json', report)
            db.commit(); transaction.commit()
            print('Prepared separate notice/version/analysis/case graph; J13 preserved.')
            print('MANIFEST=' + str(folder / 'setup.private.json'))
        except Exception:
            transaction.rollback(); raise
        finally:
            db.close()


if __name__ == '__main__':
    main()
