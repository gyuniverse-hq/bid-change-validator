"""고정된 두 원문 스냅샷과 의미 그래프를 읽기 전용으로 비교한다.

순서 기반 REQ ID와 업종 값 자체를 버전 간 identity로 사용하지 않는다.
동일 원문의 추출 차이는 분석 불일치다. 모호한 대응은 추가·삭제로 확정하지 않는다.
"""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import re
import unicodedata

from .document import GraphError, fingerprint, validate_snapshot, source_complete, decision_meaning, relation_fingerprint, snapshot_plan_version

COMPARE_VERSION = 'qualification-graph-comparison-v1'
_REVIEW = {'REVIEW_REQUIRED', 'ANALYSIS_INCONSISTENCY'}


def _text(value: str) -> str:
    # 숫자/괄호/부정/논리 기호를 보존한다. 내부 공백을 삭제해 '1 2'를 '12'로 만들지 않는다.
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', value)).strip()


def _usable(decision):
    return decision is not None and decision.status in {'REQUIREMENT','NOT_REQUIREMENT'} and not decision.pending_codes


def compare_document_graphs(before: dict, after: dict) -> dict:
    bsource, binv, bd = validate_snapshot(before)
    asource, ainv, ad = validate_snapshot(after)
    if bsource.notice_id != asource.notice_id:
        raise GraphError('DIFFERENT_NOTICE_COMPARISON')
    bdocs, adocs = defaultdict(list), defaultdict(list)
    for unit in binv.units:
        bdocs[unit.candidate.document_id].append(unit)
    for unit in ainv.units:
        adocs[unit.candidate.document_id].append(unit)
    bm = {doc['id']: doc for doc in before['document_manifest']}
    am = {doc['id']: doc for doc in after['document_manifest']}
    doc_pairs = []
    remaining_b, remaining_a = set(bdocs), set(adocs)
    # 내용 동일 또는 파일명+수집필드가 유일한 문서만 연결한다. 업로드 순서는 identity가 아니다.
    def match_by(key):
        left, right = defaultdict(list), defaultdict(list)
        for doc in sorted(remaining_b): left[key(doc, bdocs, bm)].append(doc)
        for doc in sorted(remaining_a): right[key(doc, adocs, am)].append(doc)
        for signature in sorted(set(left) & set(right)):
            if signature and len(left[signature]) == len(right[signature]) == 1:
                b, a = left[signature][0], right[signature][0]
                doc_pairs.append((b, a)); remaining_b.remove(b); remaining_a.remove(a)
    match_by(lambda doc, units, _: fingerprint([_text(u.candidate.text) for u in units[doc]]))
    match_by(lambda doc, _, manifest: _text(manifest[doc].get('name', ''))+'|'+manifest[doc].get('source_field','')
             if manifest[doc].get('name') else '')
    complete = source_complete(before) and source_complete(after)
    rows, aliases_b, aliases_a, issues = [], {}, {}, []
    if not complete:
        issues.append('SOURCE_INPUT_INCOMPLETE')
    if before['semantic_version'] != after['semantic_version'] or before['relation_version'] != after['relation_version']:
        issues.append('ANALYSIS_CONTRACT_CHANGED')
    plan_changed = snapshot_plan_version(before) != snapshot_plan_version(after)
    if plan_changed:
        issues.append('CANDIDATE_PLAN_CHANGED')
    same_source = complete and sorted(_text(''.join(u.candidate.text for u in units)) for units in bdocs.values()) == sorted(
        _text(''.join(u.candidate.text for u in units)) for units in adocs.values())
    serial = 0
    def append(bunit, aunit, alignment, confident=True):
        nonlocal serial
        serial += 1
        bk = bunit.candidate.candidate_id if bunit else None
        ak = aunit.candidate.candidate_id if aunit else None
        b, a = bd.get(bk), ad.get(ak)
        bmng, amng = decision_meaning(b), decision_meaning(a)
        equal_text = bunit is not None and aunit is not None and _text(bunit.candidate.text) == _text(aunit.candidate.text)
        reason = None
        if not confident or not complete or plan_changed or 'ANALYSIS_CONTRACT_CHANGED' in issues:
            kind, reason = 'REVIEW_REQUIRED', 'SOURCE_ALIGNMENT_OR_COMPLETENESS_UNVERIFIED'
        elif bunit is None:
            kind, reason = ('ADDED', None) if _usable(a) and a.status == 'REQUIREMENT' else ('REVIEW_REQUIRED', 'NEW_CLAUSE_UNRESOLVED')
            if a and a.status == 'NOT_REQUIREMENT': kind, reason = 'SOURCE_ADDED', None
        elif aunit is None:
            kind, reason = ('REMOVED', None) if _usable(b) and b.status == 'REQUIREMENT' else ('REVIEW_REQUIRED', 'REMOVED_CLAUSE_UNRESOLVED')
            if b and b.status == 'NOT_REQUIREMENT': kind, reason = 'SOURCE_REMOVED', None
        elif not _usable(b) or not _usable(a):
            kind, reason = ('ANALYSIS_INCONSISTENCY', 'SAME_SOURCE_DIFFERENT_COVERAGE') if equal_text and bmng != amng else ('REVIEW_REQUIRED', 'CLAUSE_ANALYSIS_INCOMPLETE')
        elif bmng == amng:
            kind = 'UNCHANGED' if equal_text else 'TEXT_CHANGED'
        elif equal_text:
            kind, reason = 'ANALYSIS_INCONSISTENCY', 'SAME_SOURCE_DIFFERENT_SEMANTICS'
        else:
            kind = 'MODIFIED'
        other_units = ainv.units if aunit is None else binv.units
        missing_unit = bunit if aunit is None else aunit
        if kind in {'ADDED','REMOVED','SOURCE_ADDED','SOURCE_REMOVED'} and any(
                _text(u.candidate.text) == _text(missing_unit.candidate.text) for u in other_units):
            kind, reason = 'REVIEW_REQUIRED', 'POSSIBLE_MOVED_OR_DUPLICATED_SOURCE'
        def side(unit, meaning):
            return None if unit is None else {'candidate_id': unit.candidate.candidate_id,
                'document_id': unit.candidate.document_id, 'block_index': unit.candidate.block_index,
                'start_offset': unit.candidate.start_offset, 'end_offset': unit.candidate.end_offset,
                'quote': unit.candidate.text, 'meaning': meaning}
        rows.append({'id': f'change-{serial}', 'change_type': kind, 'alignment': alignment,
                     'reason_code': reason, 'before': side(bunit, bmng), 'after': side(aunit, amng)})
        if bk: aliases_b[bk] = f'pair-{serial}' if ak else f'before-only-{serial}'
        if ak: aliases_a[ak] = f'pair-{serial}' if bk else f'after-only-{serial}'
    for bdoc, adoc in sorted(doc_pairs):
        left, right = bdocs[bdoc], adocs[adoc]
        bt = [_text(u.candidate.text) for u in left]
        at = [_text(u.candidate.text) for u in right]
        bcount, acount = Counter(bt), Counter(at)
        used_b, used_a = set(), set()
        for i, text in enumerate(bt):
            if bcount[text] == acount[text] == 1:
                j = at.index(text); used_b.add(i); used_a.add(j)
                append(left[i], right[j], 'EXACT_SOURCE')
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, bt, at, autojunk=False).get_opcodes():
            ib = [i for i in range(i1,i2) if i not in used_b]
            ja = [j for j in range(j1,j2) if j not in used_a]
            if not ib and not ja: continue
            if tag == 'replace' and len(ib) == len(ja) == 1 and bcount[bt[ib[0]]] == acount[at[ja[0]]] == 1:
                # 완전히 다른 조항의 한 줄 대체를 같은 요건이라고 확정하지 않는다.
                ratio = SequenceMatcher(None, bt[ib[0]], at[ja[0]], autojunk=False).ratio()
                append(left[ib[0]], right[ja[0]], 'ONE_TO_ONE_SOURCE_EDIT', ratio >= 0.55)
            elif tag == 'delete' and not ja:
                for i in ib: append(left[i], None, 'SOURCE_DELETION', bcount[bt[i]] == 1)
            elif tag == 'insert' and not ib:
                for j in ja: append(None, right[j], 'SOURCE_INSERTION', acount[at[j]] == 1)
            else:
                for i in ib: append(left[i], None, 'AMBIGUOUS_SOURCE_ALIGNMENT', False)
                for j in ja: append(None, right[j], 'AMBIGUOUS_SOURCE_ALIGNMENT', False)
            used_b.update(ib); used_a.update(ja)
    for doc in sorted(remaining_b):
        for u in bdocs[doc]: append(u, None, 'DOCUMENT_ALIGNMENT_REQUIRED', False)
    for doc in sorted(remaining_a):
        for u in adocs[doc]: append(None, u, 'DOCUMENT_ALIGNMENT_REQUIRED', False)
    if remaining_b or remaining_a or set(bm)-set(bdocs) or set(am)-set(adocs):
        issues.append('DOCUMENT_ALIGNMENT_OR_EXTRACTION_REQUIRED')
    br = relation_fingerprint(before['composition'], aliases_b)
    ar = relation_fingerprint(after['composition'], aliases_a)
    if plan_changed:
        relation_change = 'REVIEW_REQUIRED'
    elif br is None or ar is None:
        relation_change = 'REVIEW_REQUIRED'; issues.append('DOCUMENT_RELATION_UNRESOLVED')
    elif br == ar:
        relation_change = 'UNCHANGED'
    elif same_source:
        relation_change = 'ANALYSIS_INCONSISTENCY'; issues.append('SAME_SOURCE_DIFFERENT_RELATIONS')
    else:
        relation_change = 'RELATION_CHANGED'
    counts = dict(Counter(row['change_type'] for row in rows))
    review = bool(issues or any(row['change_type'] in _REVIEW for row in rows) or relation_change in _REVIEW)
    return {'contract_version': COMPARE_VERSION, 'notice_id': bsource.notice_id,
        'baseline_version_id': bsource.notice_version_id, 'current_version_id': asource.notice_version_id,
        'baseline_snapshot_sha256': before['snapshot_sha256'], 'current_snapshot_sha256': after['snapshot_sha256'],
        'same_source_text': same_source, 'comparison_status': 'REVIEW_REQUIRED' if review else 'COMPLETE',
        'changes': rows, 'counts': counts, 'relation_change': relation_change,
        'baseline_relations': before['composition'], 'current_relations': after['composition'],
        'issues': sorted(set(issues)), 'eligibility_change_asserted': False,
        'note': '원문과 저장 해석의 비교입니다. 동일 원문의 추출 차이는 공고 변경으로 확정하지 않습니다.'}
