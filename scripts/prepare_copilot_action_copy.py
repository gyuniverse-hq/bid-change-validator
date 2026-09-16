"""Create a fresh case-only J16 execution copy; never reset a consumed case."""
import argparse,json,sys
from pathlib import Path
from datetime import date,datetime,timezone
from uuid import UUID
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--label',required=True)
    args=parser.parse_args()
    from scripts.local_copilot_evaluation import configure,save
    configure()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'));folder=args.manifest.parent
    accounts=json.loads((folder/'accounts.private.json').read_text(encoding='utf-8'))
    assert args.label.startswith('J16-') and not any(a['label']==args.label for a in accounts)
    base=next(p for p in manifest['profiles'] if p['label']=='J16')
    account=next(a for a in accounts if a['label']=='J16')
    from sqlalchemy.orm import Session
    from apps.api.app.database import engine
    from apps.api.app.models import PreflightCase
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.qualification.analysis import analysis_run_response,load_qualification_analysis_run
    from apps.api.app.qualification.ask_back import answer_and_rejudge
    from apps.api.app.ask_back_schemas import QualificationAnswerCreate
    from apps.api.app.qualification.judgment import load_qualification_judgment_run
    from scripts.prepare_namwon_flow_verification import protected
    with engine.connect() as connection:
        transaction=connection.begin();db=Session(bind=connection,join_transaction_mode='create_savepoint')
        try:
            original=db.get(PreflightCase,UUID('df1f055e-8e1e-4287-a6a1-4c46b4eaa6f5'))
            assert protected(db,original)==manifest['protected_j13_sha256']
            source=db.get(PreflightCase,UUID(base['case_id']))
            case=PreflightCase(notice_id=source.notice_id,company_id=source.company_id,
                baseline_version_id=source.baseline_version_id,current_version_id=source.current_version_id,
                title=args.label+' 남원 v03 실행용 복사 [회사 프로필 변경 없음]')
            db.add(case);db.flush();runs=[]
            for prior in base['runs']:
                run=run_targeted_qualification_judgment(db,case_id=case.id,analysis_run_id=UUID(prior['analysis_id']),reference_date=date.fromisoformat(manifest['reference_date']))
                analysis=analysis_run_response(load_qualification_analysis_run(db,UUID(prior['analysis_id'])))
                requirement=next(r for r in analysis.requirements if r.scope.get('source_contract',{}).get('kind')=='SITE_VISIT')
                run.created_at=datetime.now(timezone.utc);db.flush()
                result=answer_and_rejudge(db,case_id=case.id,payload=QualificationAnswerCreate(source_judgment_run_id=run.id,
                    requirement_key=requirement.requirement_key,satisfies_requirement=True,
                    normalized_value=json.dumps({'basis':requirement.scope['source_contract']['raw_sha256'],'answers':base['canonical']['visit']}),evidence_held=False))
                current=load_qualification_judgment_run(db,result.result_judgment_run_id);current.created_at=datetime.now(timezone.utc);db.flush()
                assert {j.requirement_key:j.status for j in current.judgments}=={j['key']:j['status'] for j in prior['judgments']}
                runs.append(str(current.id))
            assert protected(db,original)==manifest['protected_j13_sha256']
            record={'label':args.label,'case_id':str(case.id),'company_id':str(case.company_id),'runs':runs,'initial_state':'MATCH_J16','profile_write':False}
            db.commit();transaction.commit()
        except Exception:transaction.rollback();raise
        finally:db.close()
    accounts.append({**account,'label':args.label,'case_id':record['case_id'],'url':'http://127.0.0.1:5181/qualification?caseId='+record['case_id']})
    save(folder/'accounts.private.json',accounts)
    manifest.setdefault('execution_copies',[]).append(record);save(args.manifest,manifest)
    print(json.dumps(record))


if __name__=='__main__':main()
