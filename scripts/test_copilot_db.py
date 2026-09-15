"""One-command PostgreSQL 16 tests. Uses only its own local Docker container.

Run: .venv-copilot-v31/Scripts/python.exe scripts/test_copilot_db.py
Existing app containers, .env, shared databases and prior logs are untouched.
"""
import json
import hashlib
import argparse
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
NAME = 'bid-copilot-test-db'
LABEL = 'bid-change-validator.copilot-test'
IMAGE = 'postgres:16-alpine'
DATABASE = 'copilot_test'
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live-model', action='store_true', help='Explicit opt-in: real API/model on synthetic test DB data')
parser.add_argument('--model-env', type=Path, default=ROOT / '.env', help='Read only OPENAI_API_KEY from this file for explicit live tests')
parser.add_argument('--browser', action='store_true', help='Real browser/UI + login/API/DB; add --live-model for budgeted model calls; UI on port 5179')
parser.add_argument('--max-usd', type=float, default=0.25)
parser.add_argument('--acceptance', action='store_true', help='Repeated completion-rubric evaluation; requires --live-model')
parser.add_argument('--dialogue', action='store_true', help='Natural reference chain and complete source scope; requires --live-model')
parser.add_argument('--snapshot', type=Path, help='Approved local Namwon snapshot; use --namwon-bundle for profile replay or --live-model for full-source explanation')
parser.add_argument('--snapshot-topic', choices=['qualification', 'submission'], default='qualification', help='Long-document live evaluation topic; one question per budgeted run')
parser.add_argument('--core-snapshots', type=Path, help='Approved Core3 source directory; live job evaluation in isolated DB')
parser.add_argument('--core-profiles', type=Path, help='Synthetic Golden fixture bundle ZIP')
parser.add_argument('--core-notice', choices=['R26BK01634263', 'R26BK01633750', 'R26BK01687120'], help='Select one Core notice for a bounded diagnostic')
parser.add_argument('--core-profiles-only', action='store_true', help='DB/rule observations for Core J01-J12, no model')
parser.add_argument('--workflow', action='store_true', help='Change/assumption/proposal/explicit-confirmation flow; requires --live-model')
parser.add_argument('--namwon-bundle', type=Path, help='Read J13-J16 from a Golden ZIP and verify product judgment in a rolled-back local DB transaction')
args = parser.parse_args()
if args.core_notice and not args.core_snapshots:
    parser.error('--core-notice requires --core-snapshots')
if args.core_profiles_only and (not args.core_snapshots or args.live_model):
    parser.error('--core-profiles-only requires --core-snapshots and forbids live model')
if args.core_snapshots:
    if not (args.live_model or args.core_profiles_only) or not args.core_profiles or args.snapshot or args.browser or args.dialogue or args.workflow or args.acceptance or args.namwon_bundle:
        parser.error('--core-snapshots requires --live-model and --core-profiles as a separate suite')
    os.environ['COPILOT_CORE_SNAPSHOTS'] = str(args.core_snapshots.resolve(strict=True))
    os.environ['COPILOT_CORE_PROFILES'] = str(args.core_profiles.resolve(strict=True))
if args.dialogue and (not args.live_model or args.workflow or args.browser or args.acceptance):
    parser.error('--dialogue requires --live-model and cannot combine with another suite')
if args.snapshot and not (args.namwon_bundle or args.live_model):
    parser.error('--snapshot requires --namwon-bundle or --live-model')
if args.snapshot and (args.browser or args.dialogue or args.workflow or args.acceptance):
    parser.error('--snapshot selects its own evaluation suite')
if args.snapshot:
    os.environ['COPILOT_NAMWON_SNAPSHOT'] = str(args.snapshot.resolve(strict=True))
if args.snapshot_topic != 'qualification' and not (args.snapshot and args.live_model):
    parser.error('--snapshot-topic submission requires --snapshot and --live-model')
os.environ['COPILOT_SNAPSHOT_TOPIC'] = args.snapshot_topic
if args.acceptance and not args.live_model:
    parser.error('--acceptance requires explicit --live-model')
if args.browser and args.acceptance:
    parser.error('--browser and --acceptance select different evaluation suites.')
if args.workflow and (not args.live_model or args.browser or args.acceptance):
    parser.error('--workflow requires --live-model and cannot combine with another evaluation suite.')
if args.namwon_bundle and (args.live_model or args.browser or args.acceptance or args.workflow):
    parser.error('--namwon-bundle selects a DB-only suite.')
if args.namwon_bundle:
    os.environ['COPILOT_NAMWON_BUNDLE'] = str(args.namwon_bundle.resolve(strict=True))
if not 0 < args.max_usd <= (2 if args.core_snapshots else 1):
    parser.error('Per-run model estimate cap is $2 for Core3, $1 otherwise, within the authorized total.')
docker = shutil.which('docker')
if not docker:
    for base in [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/DockerDesktop', Path('C:/Program Files/Docker/Docker')]:
        candidate = base / 'resources/bin/docker.exe'
        if candidate.is_file():
            docker = str(candidate)
            break
if not docker:
    raise SystemExit('Docker CLI not found. Start Docker Desktop first.')

def command(*args, check=True):
    result = subprocess.run([docker, *args], capture_output=True, text=True, encoding='utf-8')
    if check and result.returncode:
        raise SystemExit('Docker operation failed: ' + result.stderr.strip())
    return result

context = json.loads(command('context', 'inspect').stdout)[0]
endpoint = context['Endpoints']['docker']['Host']
if not endpoint.startswith(('npipe://', 'unix://')):
    raise SystemExit('Only a local Docker socket is allowed; remote Docker context refused.')
command('info', '--format', '{{.ServerVersion}}')
existing = command('container', 'inspect', NAME, check=False)
if existing.returncode:
    if command('image', 'inspect', IMAGE, check=False).returncode:
        command('pull', IMAGE)
    command('run', '-d', '--name', NAME, '--label', LABEL + '=true',
            '--publish', '127.0.0.1::5432', '--env', 'POSTGRES_DB=' + DATABASE,
            '--env', 'POSTGRES_USER=' + DATABASE, '--env', 'POSTGRES_PASSWORD=' + secrets.token_hex(24), IMAGE)
info = json.loads(command('container', 'inspect', NAME).stdout)[0]
if info['Config'].get('Labels', {}).get(LABEL) != 'true' or info['Config']['Image'] != IMAGE:
    raise SystemExit('Existing container is not owned by this test runner. Nothing changed.')
if info.get('Mounts'):
    # The official image creates an anonymous PGDATA volume. Never accept a host
    # bind mount or an explicitly shared named volume from another environment.
    if any(m['Type'] != 'volume' or len(m.get('Name', '')) != 64 for m in info['Mounts']):
        raise SystemExit('Unexpected shared storage on test container.')
if not info['State']['Running']:
    command('start', NAME)
    info = json.loads(command('container', 'inspect', NAME).stdout)[0]
values = dict(e.split('=', 1) for e in info['Config']['Env'] if '=' in e)
if values.get('POSTGRES_DB') != DATABASE or values.get('POSTGRES_USER') != DATABASE:
    raise SystemExit('Unexpected test database identity.')
bindings = info['NetworkSettings']['Ports']['5432/tcp']
if len(bindings) != 1 or bindings[0]['HostIp'] != '127.0.0.1':
    raise SystemExit('Test DB must bind only to loopback.')
port = int(bindings[0]['HostPort'])
password = values['POSTGRES_PASSWORD']
if not password.isalnum():
    raise SystemExit('Unexpected credential format in test container.')
url = f'postgresql://{DATABASE}:{password}@127.0.0.1:{port}/{DATABASE}'
os.environ.update(DATABASE_URL=url, MIGRATION_DATABASE_URL=url, DATABASE_POOL_MODE='queue',
                  APP_ENVIRONMENT='test', AUTH_REQUIRED='false', OPENAI_API_KEY='', G2B_SERVICE_KEY='',
                  PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
output = ROOT / '.ci-results' / ('copilot-db-' + stamp)
output.mkdir(parents=True)
source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for pattern in ('apps/api/app/copilot/*.py', 'apps/api/app/qualification/*.py',
                                 'apps/api/app/qualification/rules/*.py', 'apps/api/tests/test_copilot*.py', 'scripts/test_copilot_db.py')
                 for p in ROOT.glob(pattern)}
os.environ.update(DOCUMENT_STORAGE_BACKEND='LOCAL', DOCUMENT_STORAGE_PATH=str(output / 'documents'),
                  DOCUMENT_RAG_INDEX_ROOT=str(output / 'indexes'))
os.environ['COPILOT_DB_EVIDENCE'] = str(output)
os.environ['CORS_ORIGINS'] = 'http://127.0.0.1:5179'
if args.live_model:
    from dotenv import dotenv_values
    values = dotenv_values(args.model_env)
    if not values.get('OPENAI_API_KEY'):
        raise SystemExit('BLOCKED: OPENAI_API_KEY missing. No model tests executed.')
    os.environ.update(OPENAI_API_KEY=values['OPENAI_API_KEY'], OPENAI_BASE_URL='https://api.openai.com/v1',
                      COPILOT_MODEL='gpt-5.6-luna', COPILOT_LIVE_MAX_USD=str(args.max_usd))

import psycopg
for attempt in range(30):
    try:
        with psycopg.connect(url, connect_timeout=2) as connection:
            identity = connection.execute("SELECT current_database(), current_user, current_setting('server_version_num')").fetchone()
        break
    except psycopg.OperationalError:
        if attempt == 29:
            raise SystemExit('Test PostgreSQL did not become ready.')
        time.sleep(1)
if identity[:2] != (DATABASE, DATABASE) or not 160000 <= int(identity[2]) < 170000:
    raise SystemExit('PostgreSQL 16 test identity verification failed.')
print(f'Verified isolated PostgreSQL 16: {NAME}, 127.0.0.1:{port}/{DATABASE}', flush=True)

# Disable dotenv for both migration and test imports; no inherited shared URL is used.
from apps.api.app.config import Settings, get_settings
Settings.model_config['env_file'] = None
get_settings.cache_clear()
from alembic.config import Config
from alembic import command as alembic_command
sys.path.insert(0, str(ROOT / 'apps/api'))
from app.config import Settings as MigrationSettings, get_settings as migration_settings
MigrationSettings.model_config['env_file'] = None
migration_settings.cache_clear()

class Tee:
    def __init__(self, stream, file): self.stream, self.file = stream, file
    def write(self, value): self.file.write(value); self.file.flush(); return self.stream.write(value)
    def flush(self): self.file.flush(); self.stream.flush()
    def isatty(self): return False

with (output / 'run.log').open('w', encoding='utf-8') as logfile:
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Tee(old_out, logfile), Tee(old_err, logfile)
    try:
        alembic_command.upgrade(Config(str(ROOT / 'apps/api/alembic.ini')), 'head')
        print('Migration completed on verified test database.')
        # Actual local PostgreSQL is allowed; real model/external service calls are not.
        original_connect = socket.socket.connect
        def local_only(sock, address):
            if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
                return original_connect(sock, address)
            raise AssertionError('External network is forbidden in DB-only tests')
        if not args.live_model:
            socket.socket.connect = local_only
        import pytest
        tests = ['test_requirement_diff.py', 'test_copilot_product_tools.py', 'test_copilot_action_transactions.py',
                 'test_copilot_flow.py', 'test_mvp_golden_e2e.py', 'test_copilot_v31_db.py',
                 'test_copilot_rule_version_db.py', 'test_source_contract_db.py', 'test_product_baseline_regression.py']
        if args.live_model:
            tests = ['test_copilot_acceptance_live_db.py' if args.acceptance else 'test_copilot_v31_live_db.py']
        if args.browser:
            tests = ['test_copilot_v31_browser_live_db.py' if args.live_model else 'test_copilot_v31_browser_db.py']
        if args.snapshot and args.live_model:
            tests = ['test_copilot_snapshot_live_db.py']
        if args.core_snapshots:
            tests = ['test_copilot_core_profiles_db.py' if args.core_profiles_only else 'test_copilot_core_jobs_db.py']
        if args.dialogue:
            tests = ['test_copilot_dialogue_live_db.py']
        if args.workflow:
            tests = ['test_copilot_v31_workflow_live_db.py']
        if args.namwon_bundle:
            tests = ['test_copilot_namwon_snapshot_db.py' if args.snapshot else 'test_copilot_namwon_db.py']
        code = pytest.main(['-v', '-p', 'no:cacheprovider', '--tb=short', '--junitxml=' + str(output / 'tests.xml'),
                            *(['-k', args.core_notice] if args.core_notice else []),
                            *['apps/api/tests/' + t for t in tests]])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
metadata = {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'source_sha256_at_start': source_hashes,
            'container': NAME, 'container_id': info['Id'], 'image_id': info['Image'],
            'database': DATABASE, 'host': '127.0.0.1', 'port': port, 'server_version_num': identity[2],
            'tests': tests, 'exit_code': int(code), 'model': 'gpt-5.6-luna' if args.live_model else 'disabled / mocked',
            'finished_utc': datetime.now(timezone.utc).isoformat()}
(output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
print('EVIDENCE_DIR=' + str(output))
print('Test DB retained. Existing app containers and shared database untouched.')
raise SystemExit(code)
