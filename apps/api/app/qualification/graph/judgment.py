"""저장된 공고 해석을 재사용해 회사만 재판정한다. 모델 호출/저장은 하지 않는다."""
from dataclasses import asdict
from datetime import date, datetime

from ...ai.qualification.extraction.review_semantic_judgment import judge_semantic_decision
from .document import GraphError, validate_snapshot, source_complete, fingerprint


def _all(values):
    return 'UNSATISFIED' if 'UNSATISFIED' in values else 'UNKNOWN' if 'UNKNOWN' in values else 'SATISFIED'


def _any(values):
    return 'SATISFIED' if 'SATISFIED' in values else 'UNKNOWN' if 'UNKNOWN' in values else 'UNSATISFIED'


def judge_document_graph(snapshot, profile, *, case_id: str, reference_date: date,
                         anchor_dates=None, record_observations=()):
    if not isinstance(reference_date, date) or isinstance(reference_date, datetime):
        raise GraphError('REFERENCE_DATE_REQUIRED')
    _, _, decisions = validate_snapshot(snapshot)
    observations = tuple(record_observations)
    results = {key: judge_semantic_decision(d, profile, preflight_case_id=case_id, reference_date=reference_date,
        anchor_dates=anchor_dates, record_observations=observations) for key, d in decisions.items() if d.status == 'REQUIREMENT'}
    composition = snapshot['composition']
    node_results = {}
    if composition['status'] == 'COMPLETE':
        nodes = {n['id']: n for n in composition['nodes']}
        def visit(key):
            if key in node_results: return node_results[key]
            n = nodes[key]
            values = [visit(c) for c in n['children']]
            if n['operator'] == 'CLAUSE':
                result = results.get(n['candidate_id'])
                answer = result.status if result else 'UNKNOWN'
            elif n['operator'] == 'ALL_OF': answer = _all(values)
            elif n['operator'] in {'ANY_OF','EXEMPT_IF'}: answer = _any(values)
            elif n['operator'] == 'POSSIBLE_EXEMPT_IF':
                # 재량 면제는 예외 사유가 참이어도 적용 확인 없이 자동 면제하지 않는다.
                answer = _any([values[0], _all([values[1], 'UNKNOWN'])])
            else: answer = {'SATISFIED':'UNSATISFIED','UNSATISFIED':'SATISFIED','UNKNOWN':'UNKNOWN'}[values[0]]
            node_results[key] = answer
            return answer
        scoped_result = visit(composition['root_id'])
    else:
        scoped_result = 'UNKNOWN'
    overall = scoped_result if source_complete(snapshot) else 'UNKNOWN'
    return {'contract_version': 'qualification-graph-judgment-v1', 'snapshot_sha256': snapshot['snapshot_sha256'],
        'case_id': case_id, 'company_id': profile.company_id, 'reference_date': reference_date.isoformat(),
        'profile_sha256': fingerprint(profile.model_dump(mode='json')),
        'overall_status': {'SATISFIED':'eligible','UNSATISFIED':'ineligible','UNKNOWN':'insufficient_data'}[overall],
        'scoped_result': scoped_result, 'node_results': node_results,
        'clause_results': [asdict(results[k]) for k in sorted(results)],
        'source_complete': source_complete(snapshot), 'relation_status': composition['status'],
        'semantic_accuracy_verified': False, 'basis': 'SAVED_GRAPH_AND_COMPANY_SNAPSHOT'}
