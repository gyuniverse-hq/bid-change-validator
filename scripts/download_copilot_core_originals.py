"""Fetch public originals named by approved snapshots, verify hashes, no DB writes."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import sys
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def approved_url(url):
    parsed = urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname in {'www.g2b.go.kr', 'g2b.go.kr'}


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not approved_url(newurl):
            raise ValueError('Unexpected public source redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


if __name__ == '__main__':
    from apps.api.app.document_rag.readiness import corrupted_extraction
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot_dir', type=Path)
    parser.add_argument('--all-documents', action='store_true')
    args = parser.parse_args()
    output = args.snapshot_dir / 'originals'
    output.mkdir(exist_ok=True)
    report = []
    for notice_no in ('R26BK01634263', 'R26BK01633750', 'R26BK01687120'):
        snapshot = args.snapshot_dir / (notice_no + '.json')
        data = json.loads(snapshot.read_text(encoding='utf-8'))
        for doc in data['documents']:
            if not args.all_documents and not corrupted_extraction(doc.get('extracted_blocks') or []) and not doc['name'].lower().endswith('.xlsx'):
                continue
            digest = doc.get('file_sha256') or ''
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Missing original hash')
            path = output / (digest + Path(doc['name']).suffix.lower())
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('Existing original hash mismatch')
                continue
            row = {'notice_no': data['notice_no'], 'document_id': doc['id'], 'sha256': digest}
            try:
                if not approved_url(doc['url']):
                    raise ValueError('Unapproved public source host')
                with build_opener(PublicRedirects()).open(Request(doc['url'], headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as response:
                    content = response.read(25_000_001)
                if len(content) > 25_000_000 or hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError('Original hash or size mismatch')
                with path.open('xb') as file:
                    file.write(content)
                row['status'] = 'VERIFIED'
            except Exception as error:
                row.update(status='BLOCKED', reason=type(error).__name__)
            report.append(row)
    (output / ('download-report-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
