"""Local snapshot integrity and version comparison; no DB or model calls."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

PAIRS = {'R26BK01634263': ('002', '003'), 'R26BK01633750': ('000', '001'), 'R26BK01687120': ('000', '001')}


def audit(root):
    results = []
    for no, pair in PAIRS.items():
        path = root / (no + '.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        versions = {v['bid_notice_order']: v for v in data['versions']}
        row = {'notice_no': no, 'snapshot_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
               'pair': pair, 'latest_order': data['versions'][-1]['bid_notice_order'],
               'latest_notice_kind': data['versions'][-1]['notice_kind'], 'versions': [], 'comparisons': []}
        for v in data['versions']:
            docs = [d for d in data['documents'] if d['notice_version_id'] == v['id']]
            row['versions'].append({'order': v['bid_notice_order'], 'kind': v['notice_kind'],
                'change_reason': v['change_reason'], 'documents': [
                    {'name': d['name'], 'status': d['extraction_status'], 'chars': len(d['extracted_text'] or ''),
                     'hash_valid': bool(d['extracted_text']) and hashlib.sha256(d['extracted_text'].encode()).hexdigest() == d['extracted_text_sha256'],
                     'control_characters': sum(ord(c) < 32 and c not in '\n\r\t' for c in d['extracted_text'] or '')}
                    for d in docs],
                'analyses': [{'status': a['status'], 'requirements': sum(r['analysis_run_id'] == a['id'] for r in data['requirements'])}
                             for a in data['analyses'] if a['notice_version_id'] == v['id']]})
        baseline, current = (versions[order] for order in pair)
        # Attachment order changes independently of document identity.
        def identity(d):
            return 'standard' if d['source_field'] == 'stdNtceDocUrl' else d['name']
        before = {identity(d): d for d in data['documents'] if d['notice_version_id'] == baseline['id']}
        after = {identity(d): d for d in data['documents'] if d['notice_version_id'] == current['id']}
        for key in sorted(before.keys() | after.keys()):
            a, b = before.get(key), after.get(key)
            left, right = (a or {}).get('extracted_text') or '', (b or {}).get('extracted_text') or ''
            row['comparisons'].append({'field': key, 'before_name': (a or {}).get('name'), 'after_name': (b or {}).get('name'),
                'same_text': bool(left and right) and left == right,
                'diff': list(difflib.unified_diff(left.splitlines(), right.splitlines(), n=2))})
        row['metadata_changes'] = {k: [baseline['raw_json'].get(k), current['raw_json'].get(k)]
            for k in ['indstrytyLmtYn', 'bidBeginDt', 'bidClseDt', 'bidQlfctRgstDt', 'opengDt']
            if baseline['raw_json'].get(k) != current['raw_json'].get(k)}
        results.append(row)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot_dir', type=Path)
    args = parser.parse_args()
    result = audit(args.snapshot_dir)
    output = args.snapshot_dir / 'source-audit.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)
    for row in result:
        print(row['notice_no'], row['pair'], 'latest:', row['latest_order'], row['latest_notice_kind'],
              'same attachments:', sum(c['same_text'] for c in row['comparisons']), '/', len(row['comparisons']))
