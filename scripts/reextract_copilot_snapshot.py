"""Re-extract an approved local snapshot from hash-verified original files. No DB/network."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def reextract(snapshot, originals, output):
    from apps.api.app.services.document_extraction import extract_document
    from apps.api.app.document_rag.readiness import corrupted_extraction
    provenance = output.with_suffix('.provenance.json')
    if output.exists() or provenance.exists() or output.resolve() == snapshot.resolve():
        raise ValueError('Output must be a new file; original snapshot is preserved')
    data = json.loads(snapshot.read_text(encoding='utf-8'))
    changes = []
    for document in data['documents']:
        digest = document.get('file_sha256') or ''
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid original digest')
        path = originals / (digest + '.hwp')
        if not path.is_file():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Original bytes differ from approved snapshot')
        with path.open('rb') as source:
            result = extract_document(source, filename='original.hwp', content_type=document.get('content_type'))
        if not result.text or corrupted_extraction(result.blocks):
            raise ValueError('Re-extraction is still incomplete or damaged')
        new_hash = hashlib.sha256(result.text.encode()).hexdigest()
        changes.append({'document_id': document['id'], 'source_sha256': digest,
                        'old_text_sha256': document['extracted_text_sha256'], 'new_text_sha256': new_hash})
        document.update(extracted_text=result.text, extracted_blocks=result.blocks,
                        extracted_text_sha256=new_hash, extracted_char_count=len(result.text),
                        text_extractor=result.extractor, extraction_status='EXTRACTED')
    if not changes:
        raise ValueError('No verified original HWP files found')
    with output.open('x', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    with provenance.open('x', encoding='utf-8') as file:
        json.dump({'original_snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                   'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'changes': changes}, file, indent=2)
    return len(changes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--originals', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print('Re-extracted documents:', reextract(args.snapshot, args.originals, args.output))
