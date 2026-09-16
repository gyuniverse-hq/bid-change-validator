"""Resume the approved local G0-G4 pipeline without repeating accepted evidence.

Prepare a fresh graph with prepare_copilot_pipeline.py, then pass its manifest.
`plan` is read-only. `run` and `resume` have the same fail-closed resume semantics.
G3/G4 require a source-grounded review receipt in addition to browser HTTP success.
No command in this runner merges, deploys or writes a shared database.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
JOBS = ('N1','N2','N3','N4','C1','C2','C3')
REPEATS = ('C1','N4')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def candidate():
    from scripts.prepare_copilot_pipeline import source_receipt
    files = source_receipt()['files']
    # Script/report edits do not change a running product. Script hashes remain
    # in the source receipt, while product compatibility uses this smaller set.
    return {p:h for p,h in files.items() if product_file(p)}


def product_file(path):
    return path.startswith(('apps/api/app/','apps/web/')) and not path.startswith('apps/web/scripts/')


def basis_matches(receipt, current):
    recorded = receipt.get('source',{}).get('files',{})
    return {p:h for p,h in recorded.items() if product_file(p)} == current


def verified_basis(receipt,current,folder):
    if basis_matches(receipt,current):return True
    # A read-only browser receipt can cover an explicitly bounded display-only
    # patch. Never rerun model calls merely to redraw identical saved answers.
    path=folder/'ui-recheck.json'
    if not path.is_file():return False
    review=read(path)
    recorded={p:h for p,h in receipt.get('source',{}).get('files',{}).items() if product_file(p)}
    changed={p for p in set(recorded)|set(current) if recorded.get(p)!=current.get(p)}
    if (review.get('status')!='PASS' or review.get('product')!=current or not changed
            or not changed<=set(review.get('covered_paths',[]))
            or any(not p.startswith('apps/web/') for p in changed)
            or not review.get('checks') or not all(c.get('status')=='PASS' for c in review['checks'])
            or not review.get('artifacts')):return False
    return all((ROOT/a['path']).is_file() and sha(ROOT/a['path'])==a['sha256'] for a in review['artifacts'])


def reviewed_job(path, current):
    report = read(path)
    if not verified_basis(report.get('runtime',{}), current,path.parent.parent):
        return 'STALE_PRODUCT'
    if not report.get('finished_utc') and not report.get('transport') and not report.get('failure'):
        return 'IN_PROGRESS'
    if report.get('transport') != 'PASS' or report.get('failure') or report.get('blocked') or report.get('page_errors'):
        return 'FAILED_TRANSPORT'
    review_path = path.parent/'review.json'
    if not review_path.is_file():
        return 'NEEDS_SOURCE_REVIEW'
    review = read(review_path)
    if review.get('report_sha256') != sha(path):
        return 'STALE_REVIEW'
    if review.get('result') != 'PASS' or not review.get('source_checks') or not review.get('reviewer'):
        return 'FAILED_REVIEW'
    return 'PASS'


def latest_jobs(folder, current, repeat=False):
    result={}
    for job in (REPEATS if repeat else JOBS):
        prefix=job+('-repeat-' if repeat else '-')
        paths=[p for p in folder.glob(prefix+'*/report.json')
               if read(p).get('repeat',False)==repeat and verified_basis(read(p).get('runtime',{}),current,folder)]
        if paths:
            path=max(paths,key=lambda p:int(p.parent.name.rsplit('-',1)[-1]))
            result[job]={'path':str(path),'status':reviewed_job(path,current)}
        else:
            result[job]={'status':'NOT_RUN'}
    return result


def g1_status(folder, current):
    receipt_path=folder/'g1.json'
    if not receipt_path.is_file():return 'NOT_RUN'
    receipt=read(receipt_path)
    if receipt.get('product') != current:return 'STALE_PRODUCT'
    if not receipt.get('checks'):return 'UNVERIFIED'
    for check in receipt['checks']:
        path=ROOT/check['path']
        if check.get('exit_code')!=0 or not path.is_file() or sha(path)!=check.get('sha256'):
            return 'FAILED_OR_CHANGED_EVIDENCE'
        if any(not (ROOT/item['path']).is_file() or sha(ROOT/item['path'])!=item['sha256'] for item in check.get('inputs',[])):
            return 'CHANGED_INPUT_EVIDENCE'
    required={'backend','frontend-types','frontend-build','frontend-contracts','golden','copilot-contracts'}
    return 'PASS' if required <= {c['kind'] for c in receipt['checks']} else 'INCOMPLETE'


def g2_status(folder):
    m=read(folder/'manifest.json')
    if m.get('gates',{}).get('G0')!='PASS':return 'G0_REQUIRED'
    if not all(r.get('match') for p in m['profiles'] for r in p['runs']):return 'ENGINE_MISMATCH'
    for filename in ('indexes.json','lineage.json','readback.json'):
        if not (folder/filename).is_file():return 'MISSING_'+filename
        if read(folder/filename).get('protected_j13')!='UNCHANGED':return 'PRESERVATION_NOT_VERIFIED'
    indexes=read(folder/'indexes.json')
    if len(indexes.get('rows',[]))!=8 or any(r['status']!='READY' or r['repeat_build_document_calls']!=0 for r in indexes['rows']):
        return 'INDEX_NOT_READY'
    if not all(r.get('same_results') for r in read(folder/'lineage.json').get('rows',[])):
        return 'LINEAGE_MISMATCH'
    if read(folder/'readback.json').get('status')!='PASS':return 'READBACK_FAILED'
    return 'PASS'


def snapshot(folder):
    current=candidate()
    g3=latest_jobs(folder,current)
    g4=latest_jobs(folder,current,True)
    budget=read(folder.parent/'model-budget.json')
    status={'G0':read(folder/'manifest.json')['gates']['G0'], 'G1':g1_status(folder,current),
            'G2':g2_status(folder),'G3':g3,'G4':g4}
    ready=(status['G0']==status['G1']==status['G2']=='PASS'
           and all(v['status']=='PASS' for v in [*g3.values(),*g4.values()]))
    return {'checked_utc':datetime.now(timezone.utc).isoformat(), 'gates':status,
            'readiness':'READY_FOR_USER_EVALUATION' if ready else 'NOT_READY',
            'model_budget':{'cap_estimate_usd':budget['cap_estimate_usd'],
                            'reserved_estimate_usd':budget['reserved_estimate_usd'],
                            'remaining_reservation_usd':budget['cap_estimate_usd']-budget['reserved_estimate_usd']},
            'note':'Reservation upper estimates are not provider billing. Human user evaluation and final integration are not completed.'}


def execute(command, log, env, cwd=ROOT):
    with log.open('w',encoding='utf-8') as output:
        result=subprocess.run(command,cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError(f'FAILED {log}: exit {result.returncode}')


def run_g1(folder, args, env):
    if not env.get('COPILOT_CORE_SNAPSHOTS') or not env.get('COPILOT_CORE_PROFILES'):
        raise RuntimeError('Full existing DB regression needs --core-snapshots and --core-profiles (approved local copies)')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=folder/('g1-'+stamp);output.mkdir()
    checks=[]
    def check(kind, command, cwd=ROOT):
        log=output/(kind+'.log');execute(command,log,env,cwd)
        checks.append({'kind':kind,'path':str(log.relative_to(ROOT)),'sha256':sha(log),'exit_code':0})
    web=None
    try:
        try:
            urllib.request.urlopen('http://127.0.0.1:5179/login',timeout=2).close()
        except OSError:
            with (output/'test-web.log').open('w',encoding='utf-8') as log:
                web=subprocess.Popen([args.node,'scripts/local_copilot_test_web.mjs'],cwd=ROOT,env=env,
                    stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            for _ in range(60):
                if web.poll() is not None:raise RuntimeError('Test web failed to start')
                try:
                    urllib.request.urlopen('http://127.0.0.1:5179/login',timeout=1).close();break
                except OSError:time.sleep(.25)
            else:raise RuntimeError('Test web did not become ready')
        check('backend',[sys.executable,'scripts/test_copilot_db.py','--full-regression'])
        check('copilot-contracts',[sys.executable,'scripts/verify_copilot_v31.py'])
        check('golden',[sys.executable,'scripts/run_golden_regression.py','--out',str(output/'golden.json')])
        webroot=ROOT/'apps/web'
        check('frontend-types',[args.node,'node_modules/typescript/bin/tsc','--noEmit'],webroot)
        contracts=output/'frontend-contracts.log'
        with contracts.open('w',encoding='utf-8') as log:
            for suffix in ('','-actions','-integration','-semantic','-target-memory'):
                result=subprocess.run([args.node,f'scripts/check-copilot{suffix}.mjs'],cwd=webroot,env=env,stdout=log,stderr=subprocess.STDOUT)
                if result.returncode:raise RuntimeError('Frontend contract failed: '+suffix)
            result=subprocess.run([args.node,'scripts/check-requirement-diff.mjs'],cwd=webroot,env=env,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode:raise RuntimeError('Requirement display contract failed')
        checks.append({'kind':'frontend-contracts','path':str(contracts.relative_to(ROOT)),'sha256':sha(contracts),'exit_code':0})
        package=read(webroot/'node_modules/vinext/package.json')
        cli=package['bin'];cli=cli['vinext'] if isinstance(cli,dict) else cli
        check('frontend-build',[args.node,str(webroot/'node_modules/vinext'/cli),'build'],webroot)
        write(folder/'g1.json',{'product':candidate(),'checks':checks,'created_utc':datetime.now(timezone.utc).isoformat()})
    finally:
        if web is not None:
            web.terminate();web.wait(timeout=15)


def run_g2(folder,args,env):
    if not (folder/'lineage.json').is_file():
        execute([sys.executable,'scripts/complete_copilot_lineage.py','--manifest',str(folder/'manifest.json')],folder/'lineage-execution.log',env)
    if not (folder/'indexes.json').is_file():
        execute([sys.executable,'scripts/prepare_copilot_indexes.py','--manifest',str(folder/'manifest.json'),'--model-env',args.model_env],folder/'indexes-execution.log',env)
    execute([sys.executable,'scripts/check_copilot_pipeline_data.py','--manifest',str(folder/'manifest.json')],folder/'readback-execution.log',env)
    if g2_status(folder)!='PASS':raise RuntimeError('G2 evidence is incomplete')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['plan','run','resume'])
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--node',default='node')
    parser.add_argument('--playwright',help='Absolute Playwright index.mjs path; also accepts PLAYWRIGHT_MODULE')
    parser.add_argument('--core-snapshots')
    parser.add_argument('--core-profiles')
    parser.add_argument('--model-env',default='../../.env')
    parser.add_argument('--n4-label',help='Registered fresh execution copy label for G3 N4')
    parser.add_argument('--n4-repeat-label',help='Registered fresh execution copy label for G4 N4')
    parser.add_argument('--stop-after',choices=['G1','G2','G3','G4'],default='G4')
    args=parser.parse_args()
    folder=args.manifest.resolve(strict=True).parent
    allowed=(ROOT/'.ci-results/user-evaluation').resolve()
    if not folder.is_relative_to(allowed):raise RuntimeError('Only an owned local evaluation manifest is supported')
    status=snapshot(folder)
    if args.mode=='plan':print(json.dumps(status,ensure_ascii=False,indent=2));return
    env=os.environ.copy()
    if args.playwright:env['PLAYWRIGHT_MODULE']=args.playwright
    # Legacy DB browser checks take the package directory; G3 takes index.mjs.
    if args.core_snapshots:env['COPILOT_CORE_SNAPSHOTS']=str(Path(args.core_snapshots).resolve(strict=True))
    if args.core_profiles:env['COPILOT_CORE_PROFILES']=str(Path(args.core_profiles).resolve(strict=True))
    if not env.get('PLAYWRIGHT_MODULE'):raise RuntimeError('PLAYWRIGHT_MODULE is required')
    try:
        if status['gates']['G1']!='PASS':
            db_env=env.copy()
            db_env['PLAYWRIGHT_MODULE']=str(Path(env['PLAYWRIGHT_MODULE']).parent)
            run_g1(folder,args,db_env)
        if args.stop_after=='G1':return
        run_g2(folder,args,env)
        if args.stop_after=='G2':return
        runtime=read(folder.parent/'server.json')
        if not verified_basis(runtime,candidate(),folder):
            raise RuntimeError('Running API source differs. Restart the verified local evaluation server before continuing.')
        for repeat,names in ((False,JOBS),(True,REPEATS)):
            group=latest_jobs(folder,candidate(),repeat)
            if repeat and any(v['status']!='PASS' for v in latest_jobs(folder,candidate()).values()):
                raise RuntimeError('G3 needs source-grounded review before G4; no repeat calls made')
            for job in names:
                if group[job]['status']=='PASS':continue
                if group[job]['status']!='NOT_RUN':
                    raise RuntimeError(f'{job}: {group[job]["status"]}; inspect the existing report before another call. Source changes invalidate it automatically.')
                budget=read(folder.parent/'model-budget.json')
                if budget['cap_estimate_usd']-budget['reserved_estimate_usd'] < (1 if job=='N4' else .75):
                    raise RuntimeError('Insufficient remaining reservation for the next bounded Job')
                suffix='-repeat' if repeat else ''
                cmd=[args.node,'scripts/check_copilot_pipeline.mjs',str(folder),job,*(['--repeat'] if repeat else [])]
                if job=='N4' and not repeat and args.n4_label:cmd+=['--account-label',args.n4_label]
                if job=='N4' and repeat and args.n4_repeat_label:cmd+=['--account-label',args.n4_repeat_label]
                execute(cmd,folder/f'{job}{suffix}-execution.log',env)
            if any(v['status']!='PASS' for v in latest_jobs(folder,candidate(),repeat).values()):
                raise RuntimeError('Browser traces collected; source-grounded review.json receipts are required before progression')
            if not repeat and args.stop_after=='G3':return
    finally:
        status=snapshot(folder)
        write(folder/'status.json',status)
        print(json.dumps(status,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
