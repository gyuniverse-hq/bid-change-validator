"""Add approved Core snapshots/profiles to the owned local evaluation DB.

No reset, existing profile replacement, shared DB access, or model calls.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
from uuid import UUID
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.local_copilot_evaluation import configure, STATE, save, WEB_PORT

PAIRS = [('R26BK01634263', 1, '002', '003', '우치공원·005 취소공고 이전 비교'),
         ('R26BK01633750', 5, '000', '001', '구내식당'),
         ('R26BK01687120', 9, '000', '001', '한림대')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--originals', type=Path, required=True)
    parser.add_argument('--profiles', type=Path, required=True)
    args = parser.parse_args()
    identity = configure()
    existing = json.loads((STATE / 'manifest.json').read_text(encoding='utf-8'))
    if existing['database'] != identity:
        raise RuntimeError('Evaluation database identity mismatch')
    hashes = {no: hashlib.sha256((args.snapshots / (no + '.json')).read_bytes()).hexdigest() for no, *_ in PAIRS}
    manifest = STATE / 'core-manifest.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        if saved['database'] != identity or saved['source_hashes'] != hashes:
            raise RuntimeError('Existing Core evaluation differs; no overwrite')
        print('Core evaluation already exists; all answers and accounts preserved.')
        return
    with zipfile.ZipFile(args.profiles) as archive:
        cases = json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('/fixture_bundle.json'))))['cases']
    selected = [c for c in cases if c['case_id'] in {f'J{i:02}' for i in range(1, 13)}]
    if len(selected) != 12 or not all(c['synthetic'] for c in selected):
        raise RuntimeError('Expected exactly J01-J12 synthetic profiles')
    candidates = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in args.originals.iterdir()
                  if p.is_file() and not p.name.endswith('.json')}
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from apps.api.app.database import engine
    from apps.api.app.models import Company, PreflightCase
    from apps.api.app.auth_models import AppUser
    from apps.api.app.auth import hash_password
    from apps.api.app.scripts.seed_golden_v02_accounts import _replace_company_profile
    from apps.api.tests.test_copilot_namwon_snapshot_db import persist_snapshot
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.document_rag.readiness import snapshot_sources
    rows, accounts = [], []
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode='create_savepoint')
        try:
            for profile in selected:
                if db.get(Company, UUID(profile['profile']['company_id'])) or db.scalar(select(AppUser.id).where(
                        AppUser.username == 'eval-' + profile['case_id'].lower())):
                    raise RuntimeError('Core company/account already exists without manifest; no overwrite')
            for no, start, before, after, label in PAIRS:
                data = json.loads((args.snapshots / (no + '.json')).read_text(encoding='utf-8'))
                if data['notice_no'] != no or any(d['file_sha256'] not in candidates for d in data['documents']):
                    raise RuntimeError('Unexpected source identity or missing verified original')
                objects = persist_snapshot(db, data)
                versions = {v.bid_notice_order: v for v in objects['BidNoticeVersion']}
                analyses = {a.notice_version_id: a for a in objects['QualificationAnalysisRun']}
                for doc in objects['NoticeDocument']:
                    source = candidates[doc.file_sha256]
                    key = doc.file_sha256 + source.suffix.lower()
                    target = STATE / 'documents' / key
                    target.parent.mkdir(exist_ok=True)
                    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != doc.file_sha256:
                        raise RuntimeError('Local original collision')
                    if not target.exists():
                        with target.open('xb') as output:
                            output.write(source.read_bytes())
                    doc.storage_key, doc.download_status = key, 'DOWNLOADED'
                for order in (before, after):
                    if snapshot_sources(versions[order]).source_status != 'AVAILABLE':
                        raise RuntimeError('Source not ready for local review')
                for profile in [c for c in selected if start <= int(c['case_id'][1:]) < start + 4]:
                    company = _replace_company_profile(db, profile)  # Prechecked absent; creates only a new synthetic company.
                    company.name = profile['case_id'] + ' [합성·분석검수대기] ' + profile['profile_name']
                    case = PreflightCase(notice_id=versions[before].notice_id, company_id=company.id,
                        baseline_version_id=versions[before].id, current_version_id=versions[after].id,
                        title=f"{profile['case_id']} {label} {before}→{after} [과거·판정 정답 미검증]")
                    db.add(case); db.flush()
                    runs = []
                    for order in (before, after):
                        run = run_targeted_qualification_judgment(db, case_id=case.id,
                            analysis_run_id=analyses[versions[order].id].id,
                            reference_date=date.fromisoformat(profile['reference_date']))
                        runs.append({'order': order, 'judgment_id': str(run.id), 'status': run.overall_status,
                                     'analysis_status': run.analysis_status})
                    username, password = 'eval-' + profile['case_id'].lower(), secrets.token_urlsafe(18)
                    db.add(AppUser(username=username, password_hash=hash_password(password), company_id=company.id,
                                   role='USER', active=True))
                    accounts.append({'username': username, 'password': password, 'case_id': str(case.id),
                        'url': f'http://127.0.0.1:{WEB_PORT}/qualification?caseId={case.id}'})
                    rows.append({'profile': profile['case_id'], 'case_id': str(case.id), 'notice_no': no,
                                 'company_id': str(company.id), 'runs': runs})
            db.flush()
            save(STATE / 'core-accounts.private.json', accounts)
            db.commit()  # Release savepoint; outer transaction still owns atomicity.
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            db.close()
    save(manifest, {'database': identity, 'source_hashes': hashes, 'rows': rows,
        'created_at': datetime.now(timezone.utc).isoformat(), 'human_evaluation': 'NOT_RUN',
        'qualification_accuracy': 'UNVERIFIED: Q-014 stored analysis requires source review'})
    print('Added 12 synthetic Core accounts/cases. Existing Namwon data preserved. No model calls.')


if __name__ == '__main__':
    main()
