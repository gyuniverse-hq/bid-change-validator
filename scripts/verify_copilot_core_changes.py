"""Actual local HTTP/model comparison; public snapshots/synthetic accounts only."""
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
import argparse

STATE = Path(__file__).resolve().parents[1] / '.ci-results/user-evaluation'
BASE = 'http://127.0.0.1:18125/api/v1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', choices=['eval-j01', 'eval-j05', 'eval-j09'])
    args = parser.parse_args()
    accounts = json.loads((STATE / 'core-accounts.private.json').read_text(encoding='utf-8'))
    output = STATE / ('core-changes-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    rows = []
    failed = False
    try:
        for name in ('eval-j01', 'eval-j05', 'eval-j09'):
            if args.account and name != args.account:
                continue
            account = next(a for a in accounts if a['username'] == name)
            client = requests.Session()
            assert client.post(BASE + '/auth/login', json={k: account[k] for k in ('username', 'password')}, timeout=10).status_code == 200
            endpoint = BASE + '/preflight-cases/' + account['case_id'] + '/qualification-judgment-runs'
            before = client.get(endpoint, timeout=10).json()
            response = client.post(BASE + '/copilot/chat', json={
                'case_id': account['case_id'], 'response_version': '3.1', 'allow_external_processing': True,
                'message': '기준 공고와 현재 공고를 비교해줘. 실제 원문·일정·메타데이터 변경과 저장 분석 요건의 차이를 구분해서 설명해줘. 회사 판정이 바뀌었다고 추측하거나 새 판정을 실행하지 마.'},
                headers={'x-copilot-semantic-processing': 'true'}, timeout=180)
            body = response.json()
            row = {'account': name, 'http_status': response.status_code, 'body': body}
            rows.append(row)
            after = client.get(endpoint, timeout=10).json()
            envelope = body.get('envelope', {})
            row['judgment_unchanged'] = before == after
            row['pass'] = (response.status_code == 200 and before == after and not envelope.get('actions')
                and envelope.get('processing', {}).get('task_status') == 'PASS'
                and any(t.get('tool') == 'READ_CHANGES' for t in envelope.get('processing', {}).get('tools', [])))
            failed |= not row['pass']
            print(name, 'PASS' if row['pass'] else 'INCOMPLETE', flush=True)
    finally:
        output.write_text(json.dumps({'scope': 'actual HTTP/local DB/model; no business writes; not browser or human evaluation',
                                     'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('EVIDENCE=' + str(output), flush=True)
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
