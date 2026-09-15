"""Authorized public-notice-only snapshot, read-only transaction; never company data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

NOTICES = ('R26BK01634263', 'R26BK01633750', 'R26BK01687120')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    url = make_url(dotenv_values(args.env_file).get('DATABASE_URL', ''))
    if not url.host or not (url.host.endswith('.supabase.com') or url.host.endswith('.supabase.co')):
        raise RuntimeError('Expected authorized Supabase source host')
    root = Path(__file__).resolve().parents[1] / '.ci-results' / ('core-source-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    root.mkdir()
    engine = create_engine(url.set(drivername='postgresql+psycopg'), connect_args={'connect_timeout': 15,
        'options': '-c default_transaction_read_only=on -c statement_timeout=30000'}, echo=False)
    counts = []
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            assert conn.execute(text('SHOW transaction_read_only')).scalar() == 'on'
            for no in NOTICES:
                def rows(query):
                    return [r[0] for r in conn.execute(text(query), {'no': no})]
                notice = rows('SELECT to_jsonb(n) FROM bid_notices n WHERE bid_notice_no=:no')
                if len(notice) != 1:
                    raise RuntimeError('Notice identity missing or ambiguous: ' + no)
                versions = rows('SELECT to_jsonb(v) FROM bid_notice_versions v JOIN bid_notices n ON n.id=v.notice_id WHERE n.bid_notice_no=:no ORDER BY v.version_number')
                docs = rows('SELECT to_jsonb(d) FROM notice_documents d JOIN bid_notice_versions v ON v.id=d.notice_version_id JOIN bid_notices n ON n.id=v.notice_id WHERE n.bid_notice_no=:no')
                analyses = rows('SELECT DISTINCT ON (a.notice_version_id) to_jsonb(a) FROM qualification_analysis_runs a JOIN bid_notice_versions v ON v.id=a.notice_version_id JOIN bid_notices n ON n.id=v.notice_id WHERE n.bid_notice_no=:no ORDER BY a.notice_version_id,a.created_at DESC')
                aid = [a['id'] for a in analyses]
                def children(table):
                    if not aid:
                        return []
                    return [r[0] for r in conn.execute(text('SELECT to_jsonb(r) FROM '+table+' r WHERE analysis_run_id::text = ANY(:ids)'), {'ids': aid})]
                data = {'notice_no': no, 'notice': notice[0], 'versions': versions, 'documents': docs,
                    'analyses': analyses, 'requirements': children('qualification_requirements'), 'evidence': children('qualification_evidence')}
                content = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8')
                (root/(no+'.json')).write_bytes(content)
                counts.append({'notice_no': no, 'sha256': hashlib.sha256(content).hexdigest(),
                    **{k:len(data[k]) for k in ['versions','documents','analyses','requirements','evidence']}})
    engine.dispose()
    (root/'manifest.json').write_text(json.dumps({'scope':'public notice/version/document/analysis only; no company or account rows',
        'transaction':'REPEATABLE READ, READ ONLY', 'sources':counts},indent=2),encoding='utf-8')
    print(json.dumps({'directory':str(root),'sources':counts}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Snapshot failed: ' + type(error).__name__)
        raise SystemExit(1)
