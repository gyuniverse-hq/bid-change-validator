"""슬롯 경로의 의미/근거/논리 그룹을 보존하는 중복 정리.

PR #142의 재현 사례를 해결하되 같은 청크라는 이유로 인증을 삭제하지 않는다.
그래프 전용 deduplicate_atoms는 변경하지 않는다. 서로 다른 ANY_OF 연결도 남긴다.
"""
from __future__ import annotations

from collections import Counter
import json
import re
import unicodedata

from ...contracts import Evidence, QualificationRequirement
from .industry_binding import registration_alias_code

DEDUP_VERSION = 'qualification-slot-dedup-v1'


def _text(value: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', value)).strip()


def _scope(req: QualificationRequirement) -> dict:
    scope = dict(req.scope)
    # 이 mapper가 기록한 명시적 업종명/코드의 출처 메타데이터만 제외한다.
    if (req.type == 'INDUSTRY' and isinstance(req.value, str) and re.fullmatch(r'\d{4}', req.value)
            and registration_alias_code(str(scope.get('industry_name') or ''), req.raw) == req.value):
        scope.pop('industry_name', None)
        if scope.get('kind') in ('LICENSE', 'REGISTRATION', 'CERTIFICATION'):
            scope.pop('kind')
    return scope


def predicate_identity(req: QualificationRequirement) -> str:
    data = {key: getattr(req, key) for key in (
        'notice_version_id', 'type', 'value', 'operator', 'unit', 'period_months',
        'requirement_role', 'required', 'condition_complexity')}
    data['scope'] = _scope(req)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def deduplicate_requirements(requirements: list[QualificationRequirement], *,
                             evidence: list[Evidence] | None = None):
    """원문이 같은 중복 또는 좁은 업종 연결을 확인한 중복만 통합한다.

    같은 그룹 또는 서로 독립적인 단일 ALL_OF 그룹만 접는다. 다른 그룹 연결을
    삭제하지 않으며, raw 의존 판정기가 남아 있어 다른 raw는 기본적으로 합치지 않는다.
    진단에는 원래/보존 key와 양쪽 근거만 연결한다. 입력 객체는 변경하지 않는다.
    """
    refs = {item.evidence_key: item for item in (evidence or [])}
    original = list(requirements)
    groups = Counter(r.requirement_group_key or r.requirement_key for r in original)
    diagnostics, rewritten, witnesses = [], [], {}
    for req in original:
        changed = req
        if req.type in {'REGISTRATION_CERTIFICATION', 'INDUSTRY'} and isinstance(req.value, str):
            for other in original:
                if (other is req or other.type != 'INDUSTRY' or not isinstance(other.value, str)
                        or not re.fullmatch(r'\d{4}', other.value)
                        or req.notice_version_id != other.notice_version_id
                        or req.scope.get('issuer') or req.operator != other.operator
                        or any(getattr(req, k) != getattr(other, k) for k in
                            ('unit', 'period_months', 'required', 'requirement_role', 'condition_complexity'))
                        or set(req.scope) - {'kind', 'industry_name'}
                        or set(other.scope) - {'kind', 'industry_name'}):
                    continue
                # 다른 source/제약을 같은 청크 번호만으로 합치지 않는다.
                req_docs = {refs[k].document_id for k in req.evidence_keys if k in refs}
                other_docs = {refs[k].document_id for k in other.evidence_keys if k in refs}
                if (len(req_docs) != 1 or req_docs != other_docs
                        or not _text(req.raw) or _text(req.raw) not in _text(other.raw)
                        or registration_alias_code(req.value, other.raw) != other.value):
                    continue
                changed = req.model_copy(update={'type': 'INDUSTRY', 'value': other.value,
                    'scope': _scope(other)})
                witnesses[req.requirement_key] = _text(other.raw)
                witnesses[other.requirement_key] = _text(other.raw)
                diagnostics.append({'code': 'INDUSTRY_ALIAS_RESOLVED', 'raw': req.raw,
                    'original_key': req.requirement_key, 'original_type': req.type, 'original_value': req.value,
                    'code_requirement_key': other.requirement_key, 'code_value': other.value,
                    'evidence_keys': sorted(set(req.evidence_keys + other.evidence_keys))})
                break
        rewritten.append(changed)

    kept = []
    for req in rewritten:
        keeper = None
        for item in kept:
            same_group = ((item.requirement_group_key or item.requirement_key)
                          == (req.requirement_group_key or req.requirement_key))
            singleton_all = (groups[item.requirement_group_key or item.requirement_key] == 1
                and groups[req.requirement_group_key or req.requirement_key] == 1
                and (item.group_operator or 'ALL_OF') == (req.group_operator or 'ALL_OF') == 'ALL_OF')
            if (not (same_group or singleton_all)
                    or item.group_operator != req.group_operator
                    or predicate_identity(item) != predicate_identity(req)):
                continue
            same_raw = _text(item.raw) == _text(req.raw)
            proof = witnesses.get(item.requirement_key)
            if same_raw or (proof and proof == witnesses.get(req.requirement_key)):
                keeper = item
                break
        if keeper is None:
            kept.append(req)
            continue
        merged_evidence = sorted(set(keeper.evidence_keys + req.evidence_keys))
        # 불확실한 confidence를 높여 보이지 않는다. 미지정이 있으면 미지정을 유지한다.
        confidence = (min(keeper.confidence, req.confidence)
                      if keeper.confidence is not None and req.confidence is not None else None)
        kept[kept.index(keeper)] = keeper.model_copy(update={'evidence_keys': merged_evidence, 'confidence': confidence})
        diagnostics.append({'code': 'DUPLICATE_REQUIREMENT', 'raw': req.raw,
            'dropped_key': req.requirement_key, 'kept_key': keeper.requirement_key,
            'dropped_evidence_keys': list(req.evidence_keys), 'kept_evidence_keys': list(keeper.evidence_keys),
            'evidence_keys': merged_evidence, 'dedup_version': DEDUP_VERSION})
    return kept, diagnostics
