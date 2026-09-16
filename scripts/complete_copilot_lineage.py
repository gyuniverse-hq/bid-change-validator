"""Run the real revalidation service on this run's new cases; retain prior receipts."""
import argparse,json,sys
from pathlib import Path
from uuid import UUID
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.local_copilot_evaluation import configure,STATE,save


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args();identity=configure();manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    assert identity==manifest['database']
    from apps.api.app.database import SessionLocal
    from apps.api.app.models import PreflightCase
    from apps.api.app.qualification.revalidation import run_qualification_revalidation
    from apps.api.app.revalidation_schemas import QualificationRevalidationCreate
    from apps.api.app.copilot.actions import get_changed_notice
    from apps.api.app.copilot.change_impact import read_change_impact
    from scripts.prepare_namwon_flow_verification import protected
    rows=[]
    with SessionLocal() as db:
        original=db.get(PreflightCase,UUID('df1f055e-8e1e-4287-a6a1-4c46b4eaa6f5'))
        assert protected(db,original)==manifest['protected_j13_sha256']
        for profile in manifest['profiles']:
            case=db.get(PreflightCase,UUID(profile['case_id']))
            assert str(case.company_id)==profile['company_id'] and 'v03 네 조건 평가' in case.title
            baseline,current=profile['runs']
            result=run_qualification_revalidation(db,case_id=case.id,payload=QualificationRevalidationCreate(
                source_judgment_run_id=UUID(baseline['judgment_id']),baseline_analysis_run_id=UUID(baseline['analysis_id']),
                current_analysis_run_id=UUID(current['analysis_id'])))
            expected={j['key']:j['status'] for j in current['judgments']}
            actual={j.requirement_key:j.status for j in result.result.judgments}
            assert expected==actual,'Revalidation changed previously confirmed same-basis answers'
            impact=read_change_impact(db,get_changed_notice(db,case.id))
            assert impact['available'],impact
            rows.append({'label':profile['label'],'lineage_id':str(result.id),'result_judgment_id':str(result.result_judgment_run_id),
                         'same_results':True,'impact':impact})
        db.expire_all();assert protected(db,original)==manifest['protected_j13_sha256']
    save(args.manifest.parent/'lineage.json',{'rows':rows,'protected_j13':'UNCHANGED','database':identity})
    print(json.dumps({'lineage':'PASS','profiles':[r['label'] for r in rows]}))


if __name__=='__main__':main()
