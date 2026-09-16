"""Read back the prepared graph; keep the four Golden initial cases unchanged."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    args=parser.parse_args()
    from scripts.local_copilot_evaluation import configure, save
    identity=configure()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    assert identity['container_id']==manifest['database']['container_id']
    from sqlalchemy import select,text
    from apps.api.app.database import SessionLocal
    from apps.api.app.models import Company,PreflightCase,BidNoticeVersion
    from apps.api.app.judgment_models import QualificationJudgmentRun, CompanyQualificationProfileCompleteness
    from apps.api.app.qualification.judgment import build_company_profile_snapshot,_record_to_completeness
    from scripts.prepare_namwon_flow_verification import protected
    from apps.api.app.document_rag.readiness import snapshot_sources
    rows=[]
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        original=db.get(PreflightCase,UUID('df1f055e-8e1e-4287-a6a1-4c46b4eaa6f5'))
        assert protected(db,original)==manifest['protected_j13_sha256'],'Original J13 changed'
        for profile in manifest['profiles']:
            case=db.get(PreflightCase,UUID(profile['case_id']))
            assert str(case.company_id)==profile['company_id']
            company=db.get(Company,case.company_id)
            completeness=_record_to_completeness(db.get(CompanyQualificationProfileCompleteness,company.id))
            current=build_company_profile_snapshot(company,completeness).model_dump(mode='json')
            assert current==profile['runs'][0]['profile_snapshot'],'Company input changed: '+profile['label']
            for run in profile['runs']:
                record=db.get(QualificationJudgmentRun,UUID(run['judgment_id']))
                assert record and str(record.preflight_case_id)==profile['case_id']
                assert {j.requirement_key:j.status for j in record.judgments}=={j['key']:j['status'] for j in run['judgments']}
            latest=db.scalar(select(QualificationJudgmentRun).where(QualificationJudgmentRun.preflight_case_id==case.id,
                QualificationJudgmentRun.notice_version_id==case.current_version_id).order_by(QualificationJudgmentRun.created_at.desc(),QualificationJudgmentRun.id.desc()))
            if profile['label'] in {'J13','J14','J15','J16'}:
                expected={j['key']:j['status'] for j in profile['runs'][1]['judgments']}
                assert {j.requirement_key:j.status for j in latest.judgments}==expected,'Golden initial state consumed'
            rows.append({'label':profile['label'],'company_readback':'MATCH','frozen_runs':'UNCHANGED',
                'current_run':str(latest.id),'current_judgments':{j.requirement_key:j.status for j in latest.judgments}})
        index_receipt=json.loads((args.manifest.parent/'indexes.json').read_text(encoding='utf-8'))
        for row in index_receipt['rows']:
            snapshot=snapshot_sources(db.get(BidNoticeVersion,UUID(row['version_id'])))
            assert snapshot.fingerprint==row['fingerprint'],'Document basis changed'
        reserved=next((c for c in manifest.get('execution_copies',[]) if c['label']=='J16-user'),None)
        reserved_status='NOT_PREPARED'
        if reserved:
            case=db.get(PreflightCase,UUID(reserved['case_id']))
            latest=db.scalar(select(QualificationJudgmentRun).where(
                QualificationJudgmentRun.preflight_case_id==case.id,
                QualificationJudgmentRun.notice_version_id==case.current_version_id
            ).order_by(QualificationJudgmentRun.created_at.desc(),QualificationJudgmentRun.id.desc()))
            assert str(latest.id)==reserved['runs'][-1],'Reserved user evaluation case consumed'
            base=next(p for p in manifest['profiles'] if p['label']=='J16')
            assert {j.requirement_key:j.status for j in latest.judgments}=={j['key']:j['status'] for j in base['runs'][1]['judgments']}
            reserved_status='UNCHANGED'
        db.rollback()
    save(args.manifest.parent/'readback.json',{'status':'PASS','checked_utc':datetime.now(timezone.utc).isoformat(),
         'database':identity,'protected_j13':'UNCHANGED','profiles':rows,'index_fingerprints':'UNCHANGED',
         'reserved_user_case':reserved_status})
    print('PASS: original J13, four initial profiles, version runs and document fingerprints preserved')


if __name__=='__main__':main()
