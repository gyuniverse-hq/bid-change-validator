"""Bounded source memory: reuse passages only after a fresh whole-document fingerprint check."""
import json
from .v31_contracts import Fact, Source


def restore_documents(state, bundle):
    record = state.document_memory
    fingerprint = bundle.fingerprints.get('document')
    if not fingerprint or bundle.coverage.get('READ_DOCUMENT') != 'FOUND':
        return 0  # Opt-out/unavailable reads never receive old public document data.
    if record.get('scope') != bundle.scope.model_dump(mode='json') or record.get('fingerprint') != fingerprint:
        state.document_memory = {}
        return 0
    sources = [Source.model_validate(s) for s in record.get('sources', [])]
    facts = [Fact.model_validate(f) for f in record.get('facts', [])]
    if any(s.kind != 'DOCUMENT' or s.scope != bundle.scope for s in sources):
        state.document_memory = {}
        return 0
    source_ids = {s.source_id for s in sources}
    if any(f.origin_tool != 'READ_DOCUMENT' or f.scope != bundle.scope or not set(f.source_ids) <= source_ids for f in facts):
        state.document_memory = {}
        return 0
    existing = {f.fact_id for f in bundle.facts}
    added = [f for f in facts if f.fact_id not in existing]
    existing_sources = {s.source_id for s in bundle.sources}
    bundle.sources.extend(s for s in sources if s.source_id not in existing_sources)
    bundle.facts.extend(added)
    bundle.server_context['retained_document_facts'] = [f.fact_id for f in facts]
    return len(added)


def remember_documents(state, bundle, claims):
    fingerprint = bundle.fingerprints.get('document')
    if not fingerprint:
        return
    # Retain original source passages, not model-authored conclusions or completion flags.
    cited = {fid for c in claims if c.validation == 'SUPPORTED' and c.method == 'semantic' for fid in c.fact_ids}
    cited.update(bundle.server_context.get('retained_document_facts', []))
    facts = [f for f in bundle.facts if f.fact_id in cited and f.origin_tool == 'READ_DOCUMENT']
    ids = {sid for f in facts for sid in f.source_ids}
    sources = [s for s in bundle.sources if s.source_id in ids and s.kind == 'DOCUMENT']
    ids = {s.source_id for s in sources}
    facts = [f for f in facts if set(f.source_ids) <= ids]
    record = {'scope': bundle.scope.model_dump(mode='json'), 'fingerprint': fingerprint,
              'facts': [f.model_dump(mode='json') for f in facts], 'sources': [s.model_dump(mode='json') for s in sources]}
    if len(json.dumps(record, ensure_ascii=False).encode()) > 160000:
        state.document_memory = {}  # Never silently present a truncated ledger as complete.
        return
    state.document_memory = record
