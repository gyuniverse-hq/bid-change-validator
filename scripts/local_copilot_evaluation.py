"""Persistent, local-only user evaluation. Never uses a caller's DATABASE_URL.

init --snapshot PATH --bundle ZIP; serve [--model-env PATH]; verify
No reset/delete command. Init refuses populated databases without its manifest.
This developer harness reuses the snapshot replay adapter and product services.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.ci-results' / 'user-evaluation'
NAME = 'bid-copilot-evaluation-db'
LABEL = 'bid-change-validator.copilot-evaluation'
DATABASE = 'copilot_evaluation'
IMAGE = 'postgres:16-alpine'
API_PORT = 18125
WEB_PORT = 5181
SNAPSHOT_SHA = '52cb91a7da8661949ecb38b5903337274febbf88b3f20b4d76ba12f7118102f0'


def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def allowed_evaluation_request(payload, semantic_header=None):
    if not isinstance(payload, dict):
        return False
    if payload.get('response_version') == '3.1':
        return True
    return (payload.get('response_version', 'legacy') == 'legacy'
            and payload.get('intent') in {'QUALIFICATION_SUMMARY', 'REQUIRED_CHECKS', 'ACTION_REQUEST'}
            and payload.get('allow_external_processing', False) is False
            and not payload.get('public_document_question')
            and semantic_header in {None, '', 'false', '0'})


def configure():
    """Verify ownership, socket, storage, binding and database identity first."""
    docker = shutil.which('docker') or 'C:/Program Files/Docker/Docker/resources/bin/docker.exe'
    def command(*parts, check=True):
        result = subprocess.run([docker, *parts], capture_output=True, text=True, encoding='utf-8')
        if check and result.returncode:
            raise RuntimeError('Docker operation failed: ' + result.stderr.strip())
        return result
    ctx = json.loads(command('context', 'inspect').stdout)[0]
    if not ctx['Endpoints']['docker']['Host'].startswith(('npipe://', 'unix://')):
        raise RuntimeError('Remote Docker context refused')
    existing = command('inspect', NAME, check=False)
    if existing.returncode:
        command('image', 'inspect', IMAGE)  # Use the already installed test image.
        command('run', '-d', '--name', NAME, '--label', LABEL + '=true',
                '--label', 'copilot.workspace=' + str(ROOT), '--publish', '127.0.0.1::5432',
                '--env', 'POSTGRES_DB=' + DATABASE, '--env', 'POSTGRES_USER=' + DATABASE,
                '--env', 'POSTGRES_PASSWORD=' + secrets.token_hex(24), IMAGE)
    info = json.loads(command('inspect', NAME).stdout)[0]
    labels = info['Config'].get('Labels') or {}
    if labels.get(LABEL) != 'true' or labels.get('copilot.workspace') != str(ROOT) or info['Config']['Image'] != IMAGE:
        raise RuntimeError('Container ownership mismatch; nothing changed')
    if any(m['Type'] != 'volume' or len(m.get('Name', '')) != 64 for m in info.get('Mounts', [])):
        raise RuntimeError('Unexpected shared storage')
    if not info['State']['Running']:
        command('start', NAME)
        info = json.loads(command('inspect', NAME).stdout)[0]
    env = dict(v.split('=', 1) for v in info['Config']['Env'] if '=' in v)
    bindings = info['NetworkSettings']['Ports']['5432/tcp']
    if len(bindings) != 1 or bindings[0]['HostIp'] != '127.0.0.1':
        raise RuntimeError('Non-loopback DB binding refused')
    if env.get('POSTGRES_DB') != DATABASE or env.get('POSTGRES_USER') != DATABASE or not env['POSTGRES_PASSWORD'].isalnum():
        raise RuntimeError('Unexpected database identity')
    port = int(bindings[0]['HostPort'])
    url = f"postgresql://{DATABASE}:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{DATABASE}"
    os.environ.update(DATABASE_URL=url, MIGRATION_DATABASE_URL=url, DATABASE_POOL_MODE='queue',
        APP_ENVIRONMENT='local-evaluation', AUTH_REQUIRED='true', AUTH_COOKIE_SECURE='false',
        AUTH_SESSION_TTL_HOURS='24', OPENAI_API_KEY='', G2B_SERVICE_KEY='',
        OPENAI_BASE_URL='https://api.openai.com/v1', COPILOT_MODEL='gpt-5.6-luna',
        DOCUMENT_STORAGE_BACKEND='LOCAL', DOCUMENT_STORAGE_PATH=str(STATE / 'documents'),
        DOCUMENT_RAG_INDEX_ROOT=str(STATE / 'indexes'), CORS_ORIGINS=f'http://127.0.0.1:{WEB_PORT}')
    # No project dotenv, inherited model credential, or shared DB URL is used.
    from apps.api.app.config import Settings, get_settings
    Settings.model_config['env_file'] = None
    get_settings.cache_clear()
    import psycopg
    for attempt in range(30):
        try:
            with psycopg.connect(url, connect_timeout=2) as conn:
                identity = conn.execute("SELECT current_database(), current_user, current_setting('server_version_num')").fetchone()
            break
        except psycopg.OperationalError:
            if attempt == 29:
                raise
            time.sleep(1)
    if identity[:2] != (DATABASE, DATABASE) or not 160000 <= int(identity[2]) < 170000:
        raise RuntimeError('Database identity check failed')
    STATE.mkdir(parents=True, exist_ok=True)
    return {'container': NAME, 'container_id': info['Id'], 'database': DATABASE,
            'host': '127.0.0.1', 'port': port, 'server_version': identity[2]}


def initialize(args, identity):
    snapshot_bytes = args.snapshot.read_bytes()
    if hashlib.sha256(snapshot_bytes).hexdigest() != SNAPSHOT_SHA:
        raise RuntimeError('Approved snapshot hash mismatch')
    bundle_sha = hashlib.sha256(args.bundle.read_bytes()).hexdigest()
    manifest_path = STATE / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['database'] != identity or manifest['snapshot_sha256'] != SNAPSHOT_SHA or manifest['bundle_sha256'] != bundle_sha:
            raise RuntimeError('Existing evaluation identity differs; not reseeding')
        print('Already initialized; accounts, answers and judgments preserved.')
        return
    from alembic.config import Config
    from alembic import command
    sys.path.insert(0, str(ROOT / 'apps/api'))
    from app.config import Settings, get_settings
    Settings.model_config['env_file'] = None
    get_settings.cache_clear()
    command.upgrade(Config(str(ROOT / 'apps/api/alembic.ini')), 'head')
    from sqlalchemy import select, func
    from apps.api.app.database import SessionLocal
    from apps.api.app.models import Company, BidNotice, PreflightCase
    from apps.api.app.auth_models import AppUser
    from apps.api.app.auth import hash_password
    from apps.api.app.scripts.seed_golden_v02_accounts import _replace_company_profile
    from apps.api.tests.test_copilot_namwon_snapshot_db import persist_snapshot
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.qualification.rules.judgment import RULE_VERSION
    with zipfile.ZipFile(args.bundle) as z:
        names = [n for n in z.namelist() if n.endswith('/fixture_bundle.json')]
        if len(names) != 1:
            raise RuntimeError('Ambiguous fixture bundle')
        cases = json.loads(z.read(names[0]))['cases']
    selected = sorted([c for c in cases if c['case_id'] in {'J13', 'J14', 'J15', 'J16'}], key=lambda c:c['case_id'])
    if [c['case_id'] for c in selected] != ['J13', 'J14', 'J15', 'J16'] or not all(c['synthetic'] for c in selected):
        raise RuntimeError('Expected exactly four synthetic cases')
    accounts, rows = [], []
    with SessionLocal() as db:
        if any(db.scalar(select(func.count()).select_from(m)) for m in [Company, BidNotice, AppUser]):
            raise RuntimeError('Populated database without evaluation manifest; refusing overwrite')
        objects = persist_snapshot(db, json.loads(snapshot_bytes))
        versions = sorted(objects['BidNoticeVersion'], key=lambda v:v.version_number)
        assert [v.version_number for v in versions] == [1, 2]
        analyses = {a.notice_version_id:a for a in objects['QualificationAnalysisRun']}
        for source in selected:
            company = _replace_company_profile(db, source)
            company.name = source['case_id'] + ' [합성·검수대기] ' + source['profile_name']
            case = PreflightCase(notice_id=versions[0].notice_id, company_id=company.id,
                baseline_version_id=versions[0].id, current_version_id=versions[1].id,
                title=source['case_id'] + ' 남원 000→001 [과거 공고·Q-009 보류]')
            db.add(case)
            db.flush()
            runs = []
            for version in versions:
                run = run_targeted_qualification_judgment(db, case_id=case.id,
                    analysis_run_id=analyses[version.id].id, reference_date=date.fromisoformat(source['reference_date']))
                runs.append({'version':version.version_number, 'analysis_id':str(run.analysis_run_id),
                    'judgment_id':str(run.id), 'overall':run.overall_status,
                    'q009_pending':any(d.get('code') == 'SOURCE_GROUP_RELATION_UNRESOLVED' for d in run.analysis_run.diagnostics),
                    'conditions':[{'key':j.requirement_key,'status':j.status} for j in run.judgments]})
            assert runs[-1]['q009_pending']
            password = secrets.token_urlsafe(18)
            username = 'eval-' + source['case_id'].lower()
            db.add(AppUser(username=username, password_hash=hash_password(password), company_id=company.id, role='USER', active=True))
            accounts.append({'username':username,'password':password,'case_id':str(case.id),
                             'url':f'http://127.0.0.1:{WEB_PORT}/qualification?caseId={case.id}'})
            rows.append({'case':source['case_id'],'company_id':str(company.id),'case_id':str(case.id),
                'industries':[i['code'] for i in source['profile']['industries']], 'reference_date':source['reference_date'],
                'scenario_facts_not_imported_as_answers':source['scenario_facts'], 'runs':runs})
        # Write credentials before commit; a crash leaves recoverable local credentials.
        save(STATE / 'accounts.private.json', accounts)
        db.commit()
    save(manifest_path, {'created_at':datetime.now(timezone.utc).isoformat(), 'database':identity,
        'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'snapshot_sha256':SNAPSHOT_SHA,'bundle_sha256':bundle_sha,'rule_version':RULE_VERSION,
        'rows':rows,'human_evaluation':'NOT_RUN','q009':'UNRESOLVED','supplements':'Not pre-answered; J14/J15 need explicit synthetic scenario answers'})
    print('Initialized four persistent USER accounts. Credentials: ' + str(STATE / 'accounts.private.json'))


def install_budgeted_model(key):
    """Local harness adapter only; reserve before sending and never refund failures."""
    from apps.api.app.copilot import orchestration
    from apps.api.app.copilot.model_gateway import ModelGateway, BudgetExceeded
    from openai import OpenAI
    lock = threading.RLock()
    path = STATE / 'model-budget.json'
    if not path.exists():
        save(path, {'cap_estimate_usd':1.0, 'reserved_estimate_usd':0.0, 'calls':[],
                    'note':'Same conservative token-rate assumptions as development runner; not provider billing. No automatic reset.'})
    class EvaluationGateway(ModelGateway):
        def __init__(self):
            super().__init__(client=OpenAI(api_key=key, base_url='https://api.openai.com/v1', max_retries=0), model='gpt-5.6-luna')
            self.reserved = 0.0
        def call(self, stage, system, body, schema):
            with lock:
                ledger = json.loads(path.read_text(encoding='utf-8'))
                amount = self.call_cost_upper(stage)
                if ledger['reserved_estimate_usd'] + amount > min(5.0, ledger['cap_estimate_usd']) or self.reserved + amount > .25:
                    raise BudgetExceeded('LOCAL_EVALUATION_BUDGET_EXHAUSTED')
                self.reserved += amount
                ledger['reserved_estimate_usd'] += amount
                index = len(ledger['calls'])
                ledger['calls'].append({'stage':stage,'status':'reserved','reserved_estimate_usd':amount,
                                        'time':datetime.now(timezone.utc).isoformat()})
                save(path, ledger)
            started = time.monotonic()
            previous_calls = len(self.calls)
            try:
                result = super().call(stage, system, body, schema)
                status = 'succeeded'
                return result
            except Exception:
                status = 'failed'
                raise
            finally:
                with lock:
                    ledger = json.loads(path.read_text(encoding='utf-8'))
                    ledger['calls'][index]['status'] = status
                    ledger['calls'][index]['elapsed_ms'] = round((time.monotonic() - started) * 1000)
                    if len(self.calls) > previous_calls:
                        ledger['calls'][index]['usage'] = self.calls[-1].get('usage')
                    save(path, ledger)
        def embed_query(self, text):
            raise BudgetExceeded('LOCAL_EVALUATION_NO_EMBEDDING; use lexical retrieval or full document')
    orchestration.ModelGateway = EvaluationGateway


def materialize(args, identity):
    manifest = json.loads((STATE / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['database'] != identity:
        raise RuntimeError('Evaluation DB changed')
    from sqlalchemy import select
    from apps.api.app.database import SessionLocal
    from apps.api.app.models import NoticeDocument, BidNoticeVersion
    candidates = {}
    for folder in args.files:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in {'.hwp','.hwpx','.pdf'}:
                candidates[hashlib.sha256(p.read_bytes()).hexdigest()] = p
    target = STATE / 'documents'
    target.mkdir(exist_ok=True)
    rows = []
    with SessionLocal() as db:
        documents = list(db.scalars(select(NoticeDocument)))
        if len(documents) != 8 or any(d.file_sha256 not in candidates for d in documents):
            raise RuntimeError('Expected eight documents with matching local original bytes; nothing linked')
        for doc in documents:
            source = candidates[doc.file_sha256]
            key = doc.file_sha256 + source.suffix.lower()
            if doc.storage_key not in {None, key}:
                raise RuntimeError('Existing document storage differs; refusing overwrite')
            destination = target / key
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != doc.file_sha256:
                raise RuntimeError('Existing local file hash mismatch')
            if not destination.exists():
                shutil.copyfile(source, destination)
            doc.storage_key = key
            version = db.get(BidNoticeVersion, doc.notice_version_id)
            rows.append({'document_id':str(doc.id),'sha256':doc.file_sha256,
                'content_path':f'/api/v1/notices/{version.notice_id}/versions/{version.version_number}/documents/{doc.id}/content'})
        db.commit()
    save(STATE / 'document-files.json', rows)
    print('Linked eight document rows to five hash-verified original files; shared snapshot unchanged')


def serve(args, identity):
    manifest = json.loads((STATE / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['database'] != identity:
        raise RuntimeError('Evaluation DB changed')
    # Reserve port before model setup; two servers cannot race the budget file.
    sock = socket.socket()
    sock.bind(('127.0.0.1', API_PORT))
    sock.listen(128)
    if args.model_env:
        from dotenv import dotenv_values
        key = dotenv_values(args.model_env).get('OPENAI_API_KEY')
        if not key:
            raise RuntimeError('Model key absent')
        install_budgeted_model(key)
    import uvicorn
    from apps.api.app.main import app
    from fastapi import Request
    from fastapi.responses import JSONResponse
    @app.middleware('http')
    async def evaluation_scope(request: Request, call_next):
        if request.method == 'POST' and request.url.path == '/api/v1/copilot/chat':
            try:
                payload = await request.json()
            except ValueError:
                return JSONResponse({'error':{'code':'INVALID_JSON'}}, status_code=400)
            if not isinstance(payload, dict):
                return JSONResponse({'error':{'code':'INVALID_JSON'}}, status_code=400)
            if not allowed_evaluation_request(payload, request.headers.get('x-copilot-semantic-processing', '').lower()):
                return JSONResponse({'error':{'code':'LOCAL_EVALUATION_V31_ONLY'}}, status_code=400)
        response = await call_next(request)
        response.headers['X-Copilot-Evaluation'] = 'local-q009-pending'
        return response
    save(STATE / 'server.json', {'pid':os.getpid(),'api_port':API_PORT,'web_port':WEB_PORT,
        'model_enabled':bool(args.model_env),'conversation_storage':'process-memory; restart clears chat; DB answers persist'})
    uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=API_PORT, log_level='warning')).run(sockets=[sock])


def verify(identity):
    import requests
    base = f'http://127.0.0.1:{API_PORT}'
    accounts = json.loads((STATE / 'accounts.private.json').read_text(encoding='utf-8'))
    evidence = []
    preflight = requests.options(base + '/api/v1/copilot/chat', headers={
        'Origin':f'http://127.0.0.1:{WEB_PORT}', 'Access-Control-Request-Method':'POST',
        'Access-Control-Request-Headers':'content-type,x-copilot-semantic-processing'}, timeout=10)
    assert preflight.status_code == 200
    anonymous = requests.get(base + '/api/v1/preflight-cases', timeout=10)
    assert anonymous.status_code == 401
    for i, account in enumerate(accounts):
        with requests.Session() as client:
            response = client.post(base + '/api/v1/auth/login', json={k:account[k] for k in ['username','password']}, timeout=10)
            assert response.status_code == 200, response.status_code
            user = client.get(base + '/api/v1/auth/me', timeout=10).json()
            assert user['username'] == account['username'] and user['role'] == 'USER'
            own = client.get(base + '/api/v1/preflight-cases/' + account['case_id'], timeout=10)
            assert own.status_code == 200, own.status_code
            foreign = client.get(base + '/api/v1/preflight-cases/' + accounts[(i+1)%4]['case_id'], timeout=10)
            assert foreign.status_code in {403,404}, foreign.status_code
            evidence.append({'username':account['username'],'login':200,'own_case':200,'foreign_case':foreign.status_code})
            if i == 0 and (STATE / 'document-files.json').exists():
                for doc in json.loads((STATE / 'document-files.json').read_text(encoding='utf-8')):
                    response = client.get(base + doc['content_path'], timeout=15)
                    assert response.status_code == 200
                    assert hashlib.sha256(response.content).hexdigest() == doc['sha256']
    save(STATE / 'access-verification.json', {'status':'PASS','database':identity,'anonymous':401,'cors_preflight':200,'accounts':evidence,
        'scope':'Real HTTP/login/PostgreSQL; not browser, live-model or human evaluation'})
    print('PASS: four persistent accounts, own-case access, cross-company denial, anonymous denial')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init','serve','verify','documents'])
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--model-env', type=Path)
    parser.add_argument('--files', nargs='+', type=Path)
    args = parser.parse_args()
    if args.action == 'init' and (not args.snapshot or not args.bundle):
        parser.error('init requires --snapshot and --bundle')
    if args.action == 'documents' and not args.files:
        parser.error('documents requires --files directories')
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    identity = configure()
    print('Verified isolated evaluation DB:', NAME, '127.0.0.1:' + str(identity['port']), flush=True)
    if args.action == 'init': initialize(args, identity)
    elif args.action == 'serve': serve(args, identity)
    elif args.action == 'documents': materialize(args, identity)
    else: verify(identity)


if __name__ == '__main__':
    main()
