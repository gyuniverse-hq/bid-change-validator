"""Prepare a new, scoped v03 evaluation graph in the owned local PostgreSQL only.

The workbook's four-condition oracle never enters the product/model payload.
Existing users/cases/analyses/answers remain read-only. A single outer transaction
contains product service commits as savepoints; no deletion or upsert is used.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import UUID, uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.local_copilot_evaluation import configure, STATE, save

PROFILES = {
    'J13': {'codes':['1257','1227'],'exception':False},
    'J14': {'codes':['1257','1224'],'exception':False},
    'J15': {'codes':['1257'],'exception':True},
    'J16': {'codes':['1257'],'exception':None},
}
ORACLE = {'J13':['UNSATISFIED','SATISFIED'],'J14':['SATISFIED','UNSATISFIED'],
          'J15':['SATISFIED','SATISFIED'],'J16':['UNKNOWN','UNKNOWN']}


def source_receipt():
    tracked=subprocess.check_output(['git','ls-files','-z','apps/api/app','apps/web','scripts'],cwd=ROOT).decode().split('\0')
    untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z','apps/api/app','apps/web','scripts'],cwd=ROOT).decode().split('\0')
    files={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(set(tracked+untracked)) if name and (ROOT/name).is_file()}
    return {'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'files':files,'digest':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    args=parser.parse_args()
    if not args.run_id.replace('-','').isalnum(): raise ValueError('Invalid run ID')
    folder=STATE/('pipeline-'+args.run_id)
    if folder.exists(): raise RuntimeError('Run already exists; inspect its receipts instead of overwriting')
    identity=configure()
    assert json.loads((STATE/'manifest.json').read_text(encoding='utf-8'))['database']==identity
    source_path=ROOT/'.ci-results/namwon-source-reextracted.json'
    source=json.loads(source_path.read_text(encoding='utf-8'))
    if source['notice_no']!='R26BK01684863': raise ValueError('Unapproved notice')
    from sqlalchemy.orm import Session
    from apps.api.app.database import engine
    from apps.api.app.models import Company,CompanyIndustry,CompanyStaff,IndustryCode,PreflightCase
    from apps.api.app.auth_models import AppUser
    from apps.api.app.auth import hash_password
    from apps.api.app.judgment_models import CompanyQualificationProfileCompleteness
    from apps.api.app.qualification.judgment import load_qualification_judgment_run
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.qualification.source_repair import repair_analysis_from_sources
    from apps.api.app.qualification.analysis import analysis_run_response
    from apps.api.app.qualification.ask_back import answer_and_rejudge
    from apps.api.app.ask_back_schemas import QualificationAnswerCreate
    from apps.api.tests.test_copilot_namwon_snapshot_db import persist_snapshot
    from apps.api.app.document_rag.readiness import snapshot_sources
    from scripts.prepare_namwon_flow_verification import protected
    workbook=Path('C:/Users/HGLEE/Downloads/골든셋_팀검토_v03_남원데모반영.xlsx')
    if not workbook.is_file(): raise RuntimeError('Reviewed workbook unavailable')
    manifest={'run_id':args.run_id,'database':identity,'source':source_receipt(),
        'workbook_sha256':hashlib.sha256(workbook.read_bytes()).hexdigest(),
        'workbook_cells':['07_남원데모4!A5:H9','02_회사입력32!A18:H21','03_기대판정32!B18:B21'],
        'snapshot_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'scope':'v03 four reviewed conditions, separately reported from full product status',
        'reference_date':'2026-08-18','synthetic_scenario_date':'2026-08-24',
        'time_note':'규칙 비교 기준일과 합성 방문 완료 가정 시점을 구분. 8월 18일 실제 방문 완료를 주장하지 않음.',
        'oracle':ORACLE,'profiles':[],'accounts_file':'accounts.private.json',
        'gates':{'G0':'PASS','G1':'NOT_RUN','G2':'RUNNING','G3':'NOT_RUN','G4':'NOT_RUN'}}
    accounts=[]
    with engine.connect() as connection:
        transaction=connection.begin()
        db=Session(bind=connection,join_transaction_mode='create_savepoint')
        try:
            original=db.get(PreflightCase,UUID('df1f055e-8e1e-4287-a6a1-4c46b4eaa6f5'))
            before=protected(db,original)
            objects=persist_snapshot(db,source)
            versions=sorted(objects['BidNoticeVersion'],key=lambda v:v.version_number)
            assert [v.version_number for v in versions]==[1,2]
            for document in objects['NoticeDocument']:
                paths=[p for p in (STATE/'documents').iterdir() if p.is_file() and p.stem==document.file_sha256]
                assert len(paths)==1 and hashlib.sha256(paths[0].read_bytes()).hexdigest()==document.file_sha256
                document.storage_key,document.download_status=paths[0].name,'DOWNLOADED'
            analyses={a.notice_version_id:repair_analysis_from_sources(db,a) for a in objects['QualificationAnalysisRun']}
            for version in versions:
                analysis=analyses[version.id]
                for requirement in analysis.requirements:
                    scope=dict(requirement.scope or {})
                    if scope.get('source_group',{}).get('key')=='SOURCE-WASTE-INDUSTRIES':
                        scope['source_group']={'key':'SOURCE-WASTE-INDUSTRIES','relation':'AND',
                            'review_scope':'LOCAL_GOLDEN_V03_ONLY','workbook_sha256':manifest['workbook_sha256'],
                            'source_fingerprint':snapshot_sources(version).fingerprint}
                        requirement.scope=scope
                analysis.diagnostics=[d for d in analysis.diagnostics or [] if d.get('code')!='SOURCE_GROUP_RELATION_UNRESOLVED']+[
                    {'code':'LOCAL_GOLDEN_V03_INTERPRETATION','kind':'PIPELINE','severity':'INFO',
                     'message':'v03 검수의 네 조건을 해당 복제 차수에만 적용. 제품 전체 자격 및 공적 법률 해석 확정과 구분합니다.',
                     'details':{'workbook_sha256':manifest['workbook_sha256'],'source_fingerprint':snapshot_sources(version).fingerprint},'evidence_keys':[]}]
            db.flush()
            for label,config in [*PROFILES.items(),('J16-action',PROFILES['J16']),('J16-repeat',PROFILES['J16'])]:
                company=Company(name=f'{label} v03 합성 [{args.run_id}]',region_name='전북특별자치도',region_code='52',company_size='SMALL')
                db.add(company);db.flush()
                for code in config['codes']:
                    if db.get(IndustryCode,code) is None: raise RuntimeError('Required local industry code missing: '+code)
                    db.add(CompanyIndustry(company_id=company.id,industry_code=code,verified=False))
                db.add(CompanyStaff(company_id=company.id,total_count=8,verified=False))
                db.add(CompanyQualificationProfileCompleteness(company_id=company.id,region_complete=True,
                    company_size_complete=True,industries_complete=True,staff_total_complete=True,
                    staff_roles_complete=False,performances_complete=True,certifications_complete=True))
                case=PreflightCase(notice_id=versions[0].notice_id,company_id=company.id,baseline_version_id=versions[0].id,
                    current_version_id=versions[1].id,title=f'{label} 남원 v03 네 조건 평가 [종합 판정 별도]')
                db.add(case);db.flush()
                row={'label':label,'case_id':str(case.id),'company_id':str(company.id),'canonical':{
                    'industry_codes':sorted(config['codes']),'region_name':'전북특별자치도','region_code':'52',
                    'company_size':'SMALL','staff_total':8,'performances':[],'certifications':[],
                    'company_evidence_verified':False,'visit':{'site_visited':True,'visit_certificate':True},
                    'transport_exception':None if config['exception'] is None else {'disposal_permit':True,
                        'legal_transport_permission':config['exception'],'required_equipment':config['exception']}},'runs':[]}
                for version in versions:
                    run=run_targeted_qualification_judgment(db,case_id=case.id,analysis_run_id=analyses[version.id].id,reference_date=date(2026,8,18))
                    response=analysis_run_response(analyses[version.id])
                    for req in response.requirements:
                        contract=req.scope.get('source_contract',{})
                        kind=contract.get('kind')
                        answers=row['canonical']['visit'] if kind=='SITE_VISIT' else row['canonical']['transport_exception'] if kind=='WASTE_TRANSPORT' else None
                        judgment=next(j for j in run.judgments if j.requirement_key==req.requirement_key)
                        if answers is not None and judgment.status=='UNKNOWN':
                            # The harness contains service commits in savepoints.
                            # PostgreSQL now() is constant in this outer transaction;
                            # record actual execution order for these new test runs.
                            run.created_at=datetime.now(timezone.utc)
                            db.flush()
                            value=json.dumps({'basis':contract['raw_sha256'],'answers':answers},ensure_ascii=False)
                            result=answer_and_rejudge(db,case_id=case.id,payload=QualificationAnswerCreate(source_judgment_run_id=run.id,
                                requirement_key=req.requirement_key,satisfies_requirement=all(answers.values()),normalized_value=value,evidence_held=False))
                            run=load_qualification_judgment_run(db,result.result_judgment_run_id)
                            run.created_at=datetime.now(timezone.utc)
                            db.flush()
                    profile=run.profile_snapshot
                    assert sorted(i['code'] for i in profile['industries'])==row['canonical']['industry_codes']
                    assert profile['region_name']==row['canonical']['region_name'] and profile['staff']['total_count']==8
                    judgments=[{'key':j.requirement_key,'status':j.status,'reason':j.reason_code,'basis':j.basis_type} for j in run.judgments]
                    matched={r.scope.get('source_contract',{}).get('kind'):r.requirement_key for r in response.requirements}
                    selected=[j for j in judgments if j['key'] in [matched.get('WASTE_TRANSPORT'),matched.get('INDUSTRY_ANY'),matched.get('SITE_VISIT')]]
                    selected += [j for j in judgments if next(r for r in response.requirements if r.requirement_key==j['key']).type=='REGION']
                    assert len(selected)==4,'Four-condition mapping incomplete'
                    subset='UNSATISFIED' if any(j['status']=='UNSATISFIED' for j in selected) else 'UNKNOWN' if any(j['status']=='UNKNOWN' for j in selected) else 'SATISFIED'
                    expected=ORACLE[label.split('-')[0]][version.version_number-1]
                    row['runs'].append({'version':version.version_number,'version_id':str(version.id),'analysis_id':str(run.analysis_run_id),
                        'judgment_id':str(run.id),'full_status':run.overall_status,'four_conditions':subset,'expected':expected,
                        'match':subset==expected,'judgments':judgments,'selected':selected,
                        'profile_snapshot':profile,'source_fingerprint':snapshot_sources(version).fingerprint})
                username='pipeline-'+args.run_id[-8:].lower()+'-'+label.lower()
                password=secrets.token_urlsafe(18)
                db.add(AppUser(username=username,password_hash=hash_password(password),company_id=company.id,role='USER',active=True))
                accounts.append({'label':label,'username':username,'password':password,'case_id':str(case.id),
                    'url':f'http://127.0.0.1:5181/changes?caseId={case.id}'})
                manifest['profiles'].append(row)
            db.expire_all()
            assert before==protected(db,original),'Protected original changed'
            manifest['protected_j13_sha256']=before
            manifest['gates']['G2']='INPUTS_PASS' if all(r['match'] for p in manifest['profiles'] for r in p['runs']) else 'INPUTS_FAIL'
            folder.mkdir()
            save(folder/'accounts.private.json',accounts)
            save(folder/'manifest.json',manifest)
            db.commit();transaction.commit()
        except Exception:
            transaction.rollback();raise
        finally: db.close()
    print(json.dumps({'folder':str(folder),'gate':manifest['gates']['G2'],
        'profiles':[{'label':p['label'],'results':[(r['four_conditions'],r['full_status']) for r in p['runs']]} for p in manifest['profiles']]},ensure_ascii=False))


if __name__=='__main__':main()
