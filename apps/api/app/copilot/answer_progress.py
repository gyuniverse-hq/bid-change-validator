"""Reuse only server-validated prose against an identical freshly read basis.

No client-provided history, extractive fallback, action, or missing evidence can
complete a criterion. One bounded snapshot per scoped conversation.
"""
import hashlib
import json
from copy import deepcopy
from .v31_contracts import Claim


def review_key(bundle, plan, criteria):
    return hashlib.sha256(json.dumps({
        'version': 1, 'scope': bundle.scope.model_dump(mode='json'),
        'goal': plan.goal, 'criteria': [c.model_dump(mode='json') for c in criteria],
        'facts': sorted([f.model_dump(mode='json') for f in bundle.facts], key=lambda f: f['fact_id']),
        'sources': sorted([s.model_dump(mode='json') for s in bundle.sources], key=lambda s: s['source_id']),
        'fingerprints': bundle.fingerprints, 'coverage': bundle.coverage,
        'context': bundle.server_context,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def resume_review(state, key, plan):
    if not state or not plan.resume_unresolved or state.answer_review.get('key') != key:
        return [], None
    record = state.answer_review
    claims = [Claim.model_validate(c) for c in record['claims']]
    aliases = {c.claim_id: 'reviewed-' + str(i) for i, c in enumerate(claims)}
    for c in claims:
        c.claim_id = aliases[c.claim_id]
    assessment = deepcopy(record.get('assessment'))
    if assessment:
        for row in assessment.get('criteria', []):
            row['claim_ids'] = [aliases.get(cid, cid) for cid in row['claim_ids']]
    return claims, assessment


def save_review(state, key, claims, assessment):
    if state is None:
        return
    # A partial turn can preserve independently supported sentences. Completion
    # remains the server-assessed rubric, not citation count or model status alone.
    accepted = [Claim.model_validate(c.model_dump()) for c in claims
                if c.validation == 'SUPPORTED' and c.method == 'semantic']
    if len(accepted) > 60:
        state.answer_review = {}
        return
    state.answer_review = {'key': key, 'claims': [c.model_dump(mode='json') for c in accepted],
                           'assessment': assessment}


def latest_assessment(events):
    return next((e for e in reversed(events) if 'task_coverage' in e and 'criteria' in e), None)


def pending_criteria(criteria, assessment):
    if not assessment or assessment.get('reason') == 'CRITERION_SET_MISMATCH':
        return list(criteria)
    missing = set(assessment.get('missing_criterion_ids', []))
    seen = {r['criterion_id'] for r in assessment.get('criteria', [])}
    return [c for c in criteria if c.criterion_id in missing or c.criterion_id not in seen]
