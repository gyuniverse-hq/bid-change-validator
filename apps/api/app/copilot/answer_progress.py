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


def claim_basis(bundle, claim):
    facts = {f.fact_id: f for f in bundle.facts}
    sources = {s.source_id: s for s in bundle.sources}
    if not set(claim.fact_ids) <= facts.keys() or not set(claim.source_ids) <= sources.keys():
        return None
    return hashlib.sha256(json.dumps({
        'scope': bundle.scope.model_dump(mode='json'), 'fingerprints': bundle.fingerprints,
        'facts': [facts[f].model_dump(mode='json') for f in sorted(claim.fact_ids)],
        'sources': [sources[s].model_dump(mode='json') for s in sorted(claim.source_ids)],
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def evidence_basis(bundle):
    """A new question may reuse prose; changed scope, coverage or evidence may not."""
    return hashlib.sha256(json.dumps({
        'scope': bundle.scope.model_dump(mode='json'),
        'facts': sorted([f.model_dump(mode='json') for f in bundle.facts], key=lambda f: f['fact_id']),
        'sources': sorted([s.model_dump(mode='json') for s in bundle.sources], key=lambda s: s['source_id']),
        'fingerprints': bundle.fingerprints, 'coverage': bundle.coverage,
        'context': bundle.server_context,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def resume_review(state, key, plan, *, bundle=None, criteria=None):
    if not state or not plan.resume_unresolved:
        return [], None
    record = state.answer_review
    if not record:
        return [], None
    same_review = record.get('key') == key
    claims = [Claim.model_validate(c) for c in record.get('claims', [])]
    repairs = unresolved_repairs(state, bundle) if bundle is not None else []
    claims = [c for c in claims if not conflicts_with_repair(c, repairs)]
    if not same_review:
        if bundle is None or criteria is None or any(v == 'UNAVAILABLE' for v in bundle.coverage.values()):
            return [], None
        old_sources=record.get('basis_sources',{})
        if any(s.source_id in old_sources and old_sources[s.source_id] != s.model_dump(mode='json')
               for s in bundle.sources):
            return [], None
        # Retrieval may return a different subset on a follow-up. Reuse each
        # claim only if its actual references and current basis still match.
        # Requiring equality of the entire bundle unnecessarily repeats every
        # already verified manual check when a new document passage is read.
        claims = [c for c in claims if record.get('claim_basis', {}).get(c.claim_id) is not None
                  and record['claim_basis'][c.claim_id] == claim_basis(bundle, c)]
        seen={(c.text,tuple(c.fact_ids),tuple(c.source_ids)) for c in claims}
        for row in record.get('history_context',[]):
            c=Claim.model_validate(row['claim'])
            identity=(c.text,tuple(c.fact_ids),tuple(c.source_ids))
            if identity not in seen and row.get('basis') is not None and row['basis']==claim_basis(bundle,c) and not conflicts_with_repair(c, repairs):
                claims.append(c);seen.add(identity)
        accepted_ids = {c.claim_id for c in claims}
        old_definitions = record.get('criteria', [])
        old_verdicts = {r['criterion_id']: r for r in (record.get('assessment') or {}).get('criteria', [])}
        rows = []
        for criterion in criteria:
            definition = criterion.model_dump(mode='json')
            previous = next((d for d in old_definitions if all(d.get(k) == definition[k]
                            for k in ('task_kind', 'mode', 'requirement', 'fact_ids', 'submission_document', 'submission_stage', 'source_required_terms'))), None)
            row = old_verdicts.get(previous['criterion_id']) if previous else None
            met = row and row['status'] == 'MET' and row['claim_ids'] and set(row['claim_ids']) <= accepted_ids
            rows.append({'criterion_id': criterion.criterion_id, 'status': 'MET' if met else 'MISSING',
                         'claim_ids': row['claim_ids'] if met else [],
                         'reason': '같은 기준의 검증된 설명을 재사용했습니다.' if met else '현재 요청에 맞는 보완이 필요합니다.'})
        missing = [r['criterion_id'] for r in rows if r['status'] != 'MET']
        assessment = {'criteria': rows, 'missing_criterion_ids': missing,
                      'task_coverage': 'PARTIAL' if missing else 'COMPLETE'}
    else:
        assessment = deepcopy(record.get('assessment'))
    aliases = {c.claim_id: 'reviewed-' + str(i) for i, c in enumerate(claims)}
    for c in claims:
        c.claim_id = aliases[c.claim_id]
    if assessment:
        for row in assessment.get('criteria', []):
            row['claim_ids'] = [aliases.get(cid, cid) for cid in row['claim_ids']]
    return claims, assessment


def current_review_context(state, bundle):
    """Freshly matched receipts inform a new deliverable but never complete it."""
    if not state or not state.answer_review:
        return [], []
    record=state.answer_review
    def current(items):
        return [item for item in items if record.get('claim_basis',{}).get(item['claim_id'])
                == claim_basis(bundle,Claim.model_validate(item)) and claim_basis(bundle,Claim.model_validate(item)) is not None]
    accepted=current(record.get('claims',[]))
    seen={c['text'] for c in accepted}
    for row in record.get('history_context',[]):
        item=row['claim']
        if item['text'] not in seen and row.get('basis') is not None and row['basis']==claim_basis(bundle,Claim.model_validate(item)):
            accepted.append(item);seen.add(item['text'])
    repairs = unresolved_repairs(state, bundle)
    accepted = [item for item in accepted if not conflicts_with_repair(Claim.model_validate(item), repairs)]
    rejected = current(record.get('rejections',[]))
    seen = {item['text'] for item in rejected}
    rejected.extend(row['claim'] for row in repairs if row['claim']['text'] not in seen)
    return accepted,rejected


def unresolved_repairs(state, bundle):
    if not state or not state.answer_review or bundle is None:
        return []
    return [row for row in state.answer_review.get('open_repairs', [])
            if row.get('basis') is not None
            and row['basis'] == claim_basis(bundle, Claim.model_validate(row['claim']))]


def conflicts_with_repair(claim, repairs):
    """A rejected stage cannot be resurrected from an older accepted receipt."""
    for row in repairs:
        rejected = Claim.model_validate(row['claim'])
        if claim.text == rejected.text:
            return True
        if (claim.submission is not None and rejected.submission is not None
                and claim.submission.stage_kind == rejected.submission.stage_kind
                and set(claim.source_ids) & set(rejected.source_ids)):
            return True
    return False


def include_repair_criteria(state, bundle, plan, criteria):
    from .acceptance import AcceptanceCriterion
    if not plan.resume_unresolved:
        return criteria
    additions = []
    facts = {f.fact_id: f for f in bundle.facts}
    for row in unresolved_repairs(state, bundle):
        claim = Claim.model_validate(row['claim'])
        kind = 'READ_DOCUMENT' if claim.submission else next(
            (facts[fid].origin_tool for fid in claim.fact_ids if fid in facts), 'READ_DOCUMENT')
        additions.append(AcceptanceCriterion(
            criterion_id=row['criterion_id'], task_kind=kind, mode='EXPLANATION',
            requirement='이전 답변의 미해결 오류를 같은 대상·제출 단계의 새 설명으로 보완한다. '
            '다른 단계의 동명 서류나 과거에 통과했던 문장을 재사용하여 완료하지 않는다. '
            + ('제출 단계: ' + claim.submission.stage_kind + '. ' if claim.submission else '')
            + '검증 사유: ' + (claim.reason or '근거 불일치'),
            fact_ids=tuple(claim.fact_ids),
            submission_stage=claim.submission.stage_kind if claim.submission else None))
    return (*criteria, *additions)


def submission_artifact(state, bundle, plan):
    """A requested consolidated checklist keeps current verified obligation rows.

    Rows still need the same exact current source/basis. They are evidence for
    the new deliverable, never a reused verdict that the new goal is complete.
    Remaining-only questions must not regurgitate the previous checklist.
    """
    if ('체크리스트' not in plan.goal or '남은' in plan.goal or '반복하지' in plan.goal
            or not any(t.kind == 'READ_DOCUMENT' for t in plan.tasks)
            or any(v == 'UNAVAILABLE' for v in bundle.coverage.values())):
        return []
    prior, _ = current_review_context(state, bundle)
    rows, seen = [], set()
    document_facts = {f.fact_id for f in bundle.facts if f.origin_tool == 'READ_DOCUMENT'}
    for item in prior:
        row = Claim.model_validate(item)
        if row.validation != 'SUPPORTED' or row.method != 'semantic':
            continue
        if row.submission is None:
            # A verified paragraph can contain the only explanation of an
            # attendance document or deadline. Formatting is not an evidence
            # boundary: keep that current proof in a requested full checklist.
            if (not set(row.fact_ids) & document_facts
                    or not any(word in row.text for word in ('서류', '제출', '증명', '확인서'))):
                continue
            identity = ('prose', row.text)
        else:
            identity = (row.submission.document, row.submission.stage_kind,
                        row.submission.deadline, row.submission.method)
        if identity in seen:
            continue
        seen.add(identity)
        row.claim_id = 'obligation-receipt-' + str(len(rows))
        rows.append(row)
    return rows if len(rows) <= 24 else []


def visible_claims(claims, events):
    """Hide repeated prose, but deliver receipts explicitly requested as a new artifact."""
    reused = {cid for e in events if e.get('stage') == 'answer_resume' for cid in e.get('claim_ids', [])}
    requested = {cid for e in events if e.get('stage') == 'submission_artifact' for cid in e.get('display_claim_ids', [])}
    hidden = reused - requested
    return [c for c in claims if c.claim_id not in hidden], bool(hidden)


def save_review(state, key, claims, assessment, *, bundle=None, criteria=None, rejected=None):
    if state is None:
        return
    # A partial turn can preserve independently supported sentences. Completion
    # remains the server-assessed rubric, not citation count or model status alone.
    accepted = [Claim.model_validate(c.model_dump()) for c in claims
                if c.validation == 'SUPPORTED' and c.method == 'semantic']
    rejected = [Claim.model_validate(c.model_dump()) for c in rejected or []
                if c.validation != 'SUPPORTED' and c.fact_ids and c.source_ids][:12]
    repairs = list(state.answer_review.get('open_repairs', []))
    definitions = {c.criterion_id for c in criteria or []}
    missing = set((assessment or {}).get('missing_criterion_ids', []))
    if assessment and assessment.get('reason') != 'CRITERION_SET_MISMATCH':
        resolved = {r['criterion_id'] for r in assessment.get('criteria', [])
                    if r['criterion_id'] in definitions and r['status'] == 'MET'
                    and r['criterion_id'] not in missing}
        repairs = [row for row in repairs if row['criterion_id'] not in resolved]
    from .answer_validation import UNSAFE_REASONS
    for c in rejected:
        if c.validation != 'CONTRADICTED' and c.reason not in UNSAFE_REASONS:
            continue
        basis = claim_basis(bundle,c) if bundle else None
        if basis is None:
            continue
        token = hashlib.sha256((basis+c.text+(c.reason or '')).encode()).hexdigest()[:24]
        cid = 'REPAIR:' + token
        repairs = [row for row in repairs if row['criterion_id'] != cid]
        repairs.append({'criterion_id':cid,'claim':c.model_dump(mode='json'),'basis':basis})
    accepted = [c for c in accepted if not conflicts_with_repair(c, repairs)]
    if len(accepted) > 60:
        state.answer_review = {'open_repairs': repairs}
        return
    # A checks-only middle turn must not erase a previously verified submission
    # exception. These are context only; later reuse still rereads and compares
    # each exact source/basis, and never completes the new deliverable by itself.
    history=[row for row in state.answer_review.get('history_context',[])
             if not conflicts_with_repair(Claim.model_validate(row['claim']), repairs)]
    for c in accepted:
        item=c.model_dump(mode='json');basis=claim_basis(bundle,c) if bundle else None
        token=hashlib.sha256((str(basis)+c.text).encode()).hexdigest()[:24]
        item['claim_id']='context-'+token
        history=[r for r in history if r['claim']['claim_id']!=item['claim_id']]
        history.append({'claim':item,'basis':basis})
    state.answer_review = {'key': key, 'claims': [c.model_dump(mode='json') for c in accepted],
                           'open_repairs': repairs,
                           'history_context':history[-60:],
                           'assessment': assessment,
                           'evidence_basis': evidence_basis(bundle) if bundle else None,
                           'basis_sources': {s.source_id:s.model_dump(mode='json') for s in bundle.sources} if bundle else {},
                           'rejections': [c.model_dump(mode='json') for c in rejected],
                           'claim_basis': {c.claim_id: claim_basis(bundle, c) for c in [*accepted,*rejected]} if bundle else {},
                           'criteria': [c.model_dump(mode='json') for c in criteria or []]}


def latest_assessment(events):
    return next((e for e in reversed(events) if 'task_coverage' in e and 'criteria' in e), None)


def pending_criteria(criteria, assessment):
    if not assessment or assessment.get('reason') == 'CRITERION_SET_MISMATCH':
        return list(criteria)
    missing = set(assessment.get('missing_criterion_ids', []))
    seen = {r['criterion_id'] for r in assessment.get('criteria', [])}
    return [c for c in criteria if c.criterion_id in missing or c.criterion_id not in seen]
