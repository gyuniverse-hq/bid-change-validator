"""Append a source-grounded analysis revision during explicit rejudgment only."""
import hashlib
import re
from datetime import datetime, timezone
from sqlalchemy import select
from ..ai.contracts import Evidence, EvidenceLocation, QualificationRequirement
from ..analysis_models import QualificationAnalysisRun, QualificationRequirementRecord, QualificationEvidenceRecord
from ..models import BidNoticeVersion
from ..document_rag.readiness import snapshot_sources
from .rules.source_contracts import VERSION, transport_contract


def source_conditions(version):
    snapshot = snapshot_sources(version)
    accepted = {r.metadata.document_id for r in snapshot.records}
    found = {}
    for doc in version.documents:
        text = doc.extracted_text or ''
        if str(doc.id) not in accepted or hashlib.sha256(text.encode()).hexdigest() != doc.extracted_text_sha256:
            continue
        patterns = {
            'transport': r'[^\n]*폐기물수집[·ㆍ․\s]*운반업\s*\(\d{4}\)\s*등록업체[^\n]*\n\s*[○※]?\s*단,.*?\.',
            'disposal': r'폐기물중간처분업\s*\(\d{4}\)\s*또는\s*폐기물중간재활용업\s*\(\d{4}\)\s*또는\s*폐기물종합재활용업\s*\(\d{4}\)\s*등록업체',
            'visit': r'현장\s*방문\s*확인서\s*제출\s*업체에\s*한하여\s*입찰\s*참가를\s*(?:허용|인정)한다\.',
        }
        for kind, pattern in patterns.items():
            for match in re.finditer(pattern, text, re.DOTALL if kind == 'transport' else 0):
                raw = match.group(0).strip()
                if len(raw) > 1600:
                    from .judgment import QualificationJudgmentError
                    raise QualificationJudgmentError('SOURCE_CONDITION_CONFLICT', '원문 조건이 자동 보완 범위를 넘습니다. 원문을 확인해 주세요.')
                if kind == 'transport':
                    contract = transport_contract(raw)
                    if contract is None:
                        contract = {'version': VERSION, 'kind': 'UNREVIEWED', 'raw_sha256': hashlib.sha256(raw.encode()).hexdigest()}
                    value, req_type = contract.get('code'), 'INDUSTRY'
                else:
                    contract = {'version': VERSION, 'kind': 'INDUSTRY_ANY' if kind == 'disposal' else 'SITE_VISIT',
                                'raw_sha256': hashlib.sha256(raw.encode()).hexdigest()}
                    if kind == 'disposal':
                        contract['codes'] = sorted(set(re.findall(r'\((\d{4})\)', raw)))
                    value, req_type = (' / '.join(contract['codes']), 'INDUSTRY') if kind == 'disposal' else ('현장 방문 확인서 제출', 'REGISTRATION_CERTIFICATION')
                identity = re.sub(r'\s+', '', raw)
                # Conflicting versions of the same condition are never resolved by
                # document iteration order. The caller leaves those unmodified.
                found.setdefault(kind, {})[identity] = (raw, contract, value, req_type, doc, match.start())
    if any(len(rows) != 1 for rows in found.values()):
        from .judgment import QualificationJudgmentError
        raise QualificationJudgmentError('SOURCE_CONDITION_CONFLICT', '같은 차수의 원문 조건이 서로 달라 자동 보완할 수 없습니다. 원문을 확인해 주세요.')
    return snapshot, {kind: next(iter(rows.values())) for kind, rows in found.items()}


def repair_analysis_from_sources(db, run):
    from .analysis import analysis_run_response, load_qualification_analysis_run
    version = db.scalar(select(BidNoticeVersion).where(BidNoticeVersion.id == run.notice_version_id).with_for_update())
    snapshot, conditions = source_conditions(version)
    if not conditions or run.status == 'FAILED':
        return run
    marker = {'version': VERSION, 'fingerprint': snapshot.fingerprint}
    if any(d.get('code') == 'SOURCE_CONTRACTS_APPLIED' and d.get('details', {}).get('source') == marker for d in run.diagnostics or []):
        return run
    # Repeated rejudgment of an old ID reuses its already appended revision.
    candidates = db.scalars(select(QualificationAnalysisRun).where(QualificationAnalysisRun.notice_version_id == version.id)
                           .order_by(QualificationAnalysisRun.created_at.desc())).all()
    for candidate in candidates:
        if any(d.get('code') == 'SOURCE_CONTRACTS_APPLIED' and d.get('details') == {'parent_analysis_id': str(run.id), 'source': marker}
               for d in candidate.diagnostics or []):
            return load_qualification_analysis_run(db, candidate.id)
    response = analysis_run_response(run)
    requirements = list(response.requirements)
    evidence = list(response.evidence)
    # Recognizing each numbered clause does not prove the relation between them.
    # Preserve component judgments, but never silently turn the list into AND/OR.
    unresolved_group = {'transport', 'disposal'}.issubset(conditions)
    for kind, (raw, contract, value, req_type, doc, offset) in conditions.items():
        key = 'SOURCE-' + kind.upper()
        if kind == 'transport':
            matching = [r for r in requirements if r.type == 'INDUSTRY' and '폐기물수집' in r.raw]
            if len(matching) > 1:
                from .judgment import QualificationJudgmentError
                raise QualificationJudgmentError('SOURCE_CONDITION_CONFLICT', '여러 운반업 요건을 하나로 자동 보완할 수 없습니다. 원문과 분석을 확인해 주세요.')
            if matching:
                key = matching[0].requirement_key
        ev_key = 'SOURCE-' + kind.upper() + '-EVD'
        requirements = [r for r in requirements if r.requirement_key != key]
        evidence = [e for e in evidence if e.evidence_key != ev_key]
        scope = {'source_contract': contract}
        if unresolved_group and kind in {'transport', 'disposal'}:
            scope['source_group'] = {'key': 'SOURCE-WASTE-INDUSTRIES', 'relation': 'UNRESOLVED'}
        requirements.append(QualificationRequirement(requirement_key=key, notice_version_id=str(version.id),
            type=req_type, operator='MATCH', value=value, raw=raw, condition_complexity='composite',
            scope=scope, evidence_keys=[ev_key]))
        evidence.append(Evidence(evidence_key=ev_key, source_type='NOTICE_DOCUMENT', document_id=str(doc.id),
            notice_version_id=str(version.id), quote=raw, source_sha256=doc.file_sha256,
            extracted_text_sha256=doc.extracted_text_sha256,
            location=EvidenceLocation(source_line_start=doc.extracted_text[:offset].count('\n') + 1,
                                      source_line_end=doc.extracted_text[:offset + len(raw)].count('\n') + 1)))
    diagnostics = []
    for diagnostic in run.diagnostics or []:
        raw = str(diagnostic.get('details', {}).get('raw') or '')
        normalized = re.sub(r'\s+', '', raw)
        covered = next((kind for kind, row in conditions.items()
                        if len(normalized) >= 20 and (normalized in re.sub(r'\s+', '', row[0]) or re.sub(r'\s+', '', row[0]) in normalized)), None)
        if covered and diagnostic.get('kind') == 'NOTICE_FACT':
            diagnostic = {'code': 'SOURCE_CONDITION_REPLACED', 'kind': 'PIPELINE', 'severity': 'INFO',
                          'message': '원문 조건을 새 분석의 판정·확인 대상으로 연결했습니다.',
                          'details': {'previous': diagnostic}, 'evidence_keys': ['SOURCE-' + covered.upper() + '-EVD']}
        diagnostics.append(diagnostic)
    if unresolved_group:
        diagnostics.append({'code': 'SOURCE_GROUP_RELATION_UNRESOLVED', 'kind': 'NOTICE_FACT', 'severity': 'WARNING',
            'message': '처분·재활용업군과 수집·운반업군 사이의 AND/OR 관계는 원문 검수가 필요합니다. 개별 조건 결과를 전체 참가 결론으로 합산하지 않습니다.',
            'details': {'group': 'SOURCE-WASTE-INDUSTRIES'}, 'evidence_keys': ['SOURCE-DISPOSAL-EVD', 'SOURCE-TRANSPORT-EVD']})
    new = QualificationAnalysisRun(notice_version_id=version.id, contract_version=run.contract_version,
        analysis_kind=run.analysis_kind, status=run.status if snapshot.source_status == 'AVAILABLE' and not unresolved_group else 'PARTIAL', target_chunk_ids=list(run.target_chunk_ids or []),
        dropped_requirements=list(run.dropped_requirements or []), created_at=datetime.now(timezone.utc),
        diagnostics=[*diagnostics, {'code': 'SOURCE_CONTRACTS_APPLIED', 'severity': 'INFO', 'kind': 'PIPELINE',
            'message': '명시적 재판정에서 원문에 고정된 조건을 보완한 새 분석입니다. 이전 분석은 보존됩니다.',
            'details': {'parent_analysis_id': str(run.id), 'source': marker}, 'evidence_keys': []}])
    db.add(new)
    db.flush()
    for requirement in requirements:
        data = requirement.model_dump(exclude={'notice_version_id', 'value'})
        db.add(QualificationRequirementRecord(analysis_run_id=new.id, value_json=requirement.value, **data))
    for item in evidence:
        db.add(QualificationEvidenceRecord(analysis_run_id=new.id, **item.model_dump()))
    db.flush()
    return load_qualification_analysis_run(db, new.id)
