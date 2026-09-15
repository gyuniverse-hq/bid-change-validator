"""Compact evidence once, retaining complete fact/source groups within the budget."""
import json
import re


def evidence_payload(bundle, facts=None):
    facts = bundle.facts if facts is None else facts
    ids = {sid for f in facts for sid in f.source_ids}
    sources = [s for s in bundle.sources if s.source_id in ids]
    quotes = {s.source_id: s.quote for s in sources}
    scopes = {'current': bundle.scope.model_dump(mode='json')}
    def compact_scope(row):
        scope = row.pop('scope')
        ref = next((key for key, value in scopes.items() if value == scope), None)
        if ref is None:
            ref = 'scope-' + str(len(scopes))
            scopes[ref] = scope
        row['scope_ref'] = ref
        return row
    rows = []
    for fact in facts:
        row = fact.model_dump(mode='json', exclude_none=True)
        if fact.origin_tool == 'READ_DOCUMENT':
            row.pop('entity_ref', None)  # source IDs already identify the exact current chunk
        if any(fact.text == quotes.get(sid) for sid in fact.source_ids):
            row.pop('text')  # source_ids point to the sole authoritative text
        rows.append(compact_scope(row))
    # Hashes and full UI locations are verified/retained by the server. They do
    # not help the language model compare the actual source text.
    source_rows = [compact_scope(s.model_dump(mode='json', exclude_none=True,
                    include={'source_id', 'kind', 'quote', 'scope', 'document_id'})) for s in sources]
    documents = {}
    for row in source_rows:
        document_id = row.pop('document_id', None)
        if document_id:
            documents.setdefault(document_id, 'document-' + str(len(documents)))
            row['document_ref'] = documents[document_id]
    return {'scopes': scopes, 'current_scope': 'current', 'server_context': bundle.server_context,
            'facts': rows, 'sources': source_rows,
            'coverage': bundle.coverage, 'limitations': bundle.limitations}


def ranked_facts(bundle, question):
    tokens = set(re.findall(r'[가-힣A-Za-z0-9]{2,}', question))
    return sorted(bundle.facts, key=lambda f: sum(t in f.text for t in tokens), reverse=True)


def prepare_evidence(bundle, question, max_bytes=7000):
    selected, omitted = [], []
    for fact in ranked_facts(bundle, question):
        candidate = evidence_payload(bundle, selected + [fact])
        if len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) <= max_bytes:
            selected.append(fact)
        else:
            omitted.append(fact.fact_id)
    return evidence_payload(bundle, selected), omitted
