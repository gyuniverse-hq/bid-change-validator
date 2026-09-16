"""Read the two judgments pinned by a saved revalidation; never judge anew."""
from collections import Counter
import hashlib
import json
import re
from sqlalchemy import select

from ..judgment_models import QualificationJudgmentRun
from ..revalidation_models import QualificationRevalidationRun
from ..qualification.rules.judgment import RULE_VERSION


def structured_change_kind(change):
    """Explain value changes separately from source/provenance edits; never skip revalidation."""
    before, after = change.baseline, change.current
    if before is None:
        return 'ADDED'
    if after is None:
        return 'REMOVED'
    def decision(item):
        from copy import deepcopy
        fields = ('type','operator','value','unit','period_months','required',
                  'requirement_role','condition_complexity','group_operator')
        values = {key:getattr(item,key,None) for key in fields}
        scope = deepcopy(getattr(item,'scope',None) or {})
        for key, field in [('source_contract','raw_sha256'),('source_group','workbook_sha256'),('source_group','source_fingerprint')]:
            if isinstance(scope.get(key),dict):scope[key].pop(field,None)
        values['scope']=scope
        return json.dumps(values,ensure_ascii=False,sort_keys=True,default=str)
    return 'STRUCTURED_VALUE_SAME' if decision(before)==decision(after) else 'STRUCTURED_VALUE_CHANGED'


def change_impact_request(message):
    text = re.sub(r'\s+', '', message)
    return (any(word in text for word in ('변경', '바뀌', '전후', '기준공고', '이전공고'))
            and any(word in text for word in ('판정', '참가', '우리회사', '영향', '재검증')))


def compare_saved_impact(lineage, before, after, provenance, changes):
    unavailable = lambda reason: {'available': False, 'reason': reason}
    if lineage is None:
        return unavailable('현재 판정과 연결된 재검증 실행 기록이 없습니다. 전후 판정의 원인을 단정할 수 없습니다.')
    if before is None or after is None:
        return unavailable('재검증의 기준 또는 결과 판정이 없어 전후 영향을 비교할 수 없습니다.')
    p = provenance
    expected = (
        lineage.preflight_case_id == p.case_id,
        lineage.source_judgment_run_id == before.id == p.baseline.judgment_run_id,
        lineage.result_judgment_run_id == after.id == p.current.judgment_run_id,
        lineage.baseline_analysis_run_id == before.analysis_run_id == p.baseline.analysis_run_id,
        lineage.current_analysis_run_id == after.analysis_run_id == p.current.analysis_run_id,
        before.notice_version_id == p.baseline.notice_version_id,
        after.notice_version_id == p.current.notice_version_id,
        before.analysis_status == p.baseline.analysis_status,
        after.analysis_status == p.current.analysis_status,
    )
    if not all(expected) or any(r.preflight_case_id != p.case_id or r.company_id != p.company_id for r in (before, after)):
        return unavailable('재검증 기록이 현재 사례·공고 버전·분석·판정과 일치하지 않습니다. 현재 판정의 변화로 해석하지 않습니다.')
    if before.rule_version != after.rule_version or after.rule_version != RULE_VERSION or before.reference_date != after.reference_date:
        return unavailable('전후 판정의 규칙 또는 기준일이 달라 공고 변경만의 영향으로 비교할 수 없습니다.')
    if (not before.profile_snapshot or before.profile_snapshot != after.profile_snapshot
            or before.profile_snapshot.get('company_id') != str(p.company_id)):
        return unavailable('전후 판정에 사용한 회사정보가 달라 공고 변경만의 영향으로 비교할 수 없습니다.')
    old = {j.requirement_key: j for j in before.judgments}
    new = {j.requirement_key: j for j in after.judgments}
    if (len(old) != len(before.judgments) or len(new) != len(after.judgments)
            or set(old) != {c.baseline_key for c in changes if c.baseline_key}
            or set(new) != {c.current_key for c in changes if c.current_key}):
        return unavailable('전후 요건과 판정의 연결이 불완전하여 영향 비교를 보류합니다.')
    rows = []
    for c in changes:
        b, a = old.get(c.baseline_key), new.get(c.current_key)
        req = c.current or c.baseline
        rows.append({'type': req.type, 'raw': req.raw, 'change_type': c.change_type,
                     'before_value': c.baseline.value if c.baseline else None,
                     'after_value': c.current.value if c.current else None,
                     'before_status': b.status if b else None, 'after_status': a.status if a else None,
                     'before_basis': b.basis_type if b else None, 'after_basis': a.basis_type if a else None,
                     'revalidated': bool(c.current_key in lineage.revalidated_keys)})
    return {'available': True, 'lineage_id': str(lineage.id),
            'source_judgment_id': str(before.id), 'result_judgment_id': str(after.id),
            'reference_date': str(after.reference_date), 'rule_version': after.rule_version,
            'profile_equal': True,
            'profile_sha256': hashlib.sha256(json.dumps(before.profile_snapshot, sort_keys=True, default=str).encode()).hexdigest(),
            'profile_industry_codes': [v.get('code') for v in before.profile_snapshot.get('industries', [])],
            'before_status': before.overall_status, 'after_status': after.overall_status,
            'before_counts': dict(Counter(j.status for j in before.judgments)),
            'after_counts': dict(Counter(j.status for j in after.judgments)),
            'partial': before.analysis_status == 'PARTIAL' or after.analysis_status == 'PARTIAL',
            'group_relation_unresolved': any(
                (r.scope or {}).get('source_group', {}).get('relation') == 'UNRESOLVED'
                for c in changes for r in (c.baseline, c.current) if r is not None),
            'rows': rows}


def read_change_impact(db, change_result):
    p = change_result.provenance
    with db.no_autoflush:
        lineage = db.scalar(select(QualificationRevalidationRun).where(
            QualificationRevalidationRun.preflight_case_id == p.case_id,
            QualificationRevalidationRun.result_judgment_run_id == p.current.judgment_run_id,
        ).order_by(QualificationRevalidationRun.created_at.desc(), QualificationRevalidationRun.id.desc()).limit(1))
        before = db.get(QualificationJudgmentRun, lineage.source_judgment_run_id) if lineage else None
        after = db.get(QualificationJudgmentRun, lineage.result_judgment_run_id) if lineage else None
        return compare_saved_impact(lineage, before, after, p, change_result.changes)


STATUS = {'SATISFIED': '충족', 'UNSATISFIED': '미달', 'UNKNOWN': '확인 필요',
          'eligible': '참가 가능', 'ineligible': '참가 불가', 'insufficient_data': '판정 보류', None: '해당 요건 없음'}


def impact_text(impact):
    if not impact['available']:
        return impact['reason']
    lines = [f"저장된 재검증의 전후 판정: {STATUS[impact['before_status']]} → {STATUS[impact['after_status']]}.",
             '두 판정은 같은 회사정보 snapshot·같은 규칙·같은 기준일을 사용했습니다. 현재 회사정보를 새로 확인한 것은 아닙니다.']
    lines.append('판정 당시 저장 회사정보의 업종코드: ' + ', '.join(str(v) for v in impact['profile_industry_codes']) + '. 실제 등록증 검증을 뜻하지 않습니다.')
    for row in impact['rows']:
        lines.append(f"요건: {row['raw']} / 비교값: {row['before_value']} → {row['after_value']} / "
                     f"판정: {STATUS[row['before_status']]} → {STATUS[row['after_status']]} / "
                     + ('이번 재검증에서 다시 판정함.' if row['revalidated'] else '기준 판정을 이어받았거나 삭제된 요건입니다.'))
    if impact['partial']:
        lines.append('분석이 부분 완료여서 전체 참가자격의 법적 확정이 아닙니다. 미확정 원문 해석은 보류합니다.')
    if impact['group_relation_unresolved']:
        lines.append('업종군 사이 결합 관계(AND/OR)는 미확정입니다. 두 업종군을 반드시 동시에 충족해야 한다거나 어느 하나로 대체할 수 있다고 확정하지 않습니다. 개별 업종 요건의 충족과 별개로 발주기관 확인 또는 검수된 원문 해석이 필요합니다.')
    return '\n'.join(lines)
