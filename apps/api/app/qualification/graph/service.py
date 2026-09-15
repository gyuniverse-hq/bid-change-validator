"""그래프 전용 저장 서비스. 기존 슬롯 분석·Copilot의 최신 결과를 바꾸지 않는다.

회사 자료는 분석 호출에 포함하지 않는다. 비교는 지정된 실행 두 개를 읽기만 한다.
원문/프로필의 저장 전 대조는 낙관적 확인이며 DB 잠금/CAS 보증을 뜻하지 않는다.
"""
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import BidNoticeVersion, PreflightCase
from ...judgment_models import CompanyQualificationProfileCompleteness
from ...config import get_settings
from ..analysis import _load_notice_version, build_qualification_analysis_input
from ..analysis_execution import source_basis, product_review_options
from ..judgment import _load_company, _record_to_completeness, build_company_profile_snapshot
from ..rules.judgment import RULE_VERSION
from .models import QualificationGraphRun, QualificationGraphJudgmentRun
from .document import VERSION, GraphError, extract_document_graph, validate_snapshot, graph_status, fingerprint
from .comparison import compare_document_graphs
from .judgment import judge_document_graph


def _case(db: Session, case_id: UUID):
    case = db.get(PreflightCase, case_id)
    if case is None: raise GraphError('CASE_NOT_FOUND')
    return case


def _allowed_version_ids(case):
    return {v for v in (case.baseline_version_id, case.current_version_id) if v is not None}


def _case_basis(case):
    return (case.notice_id, case.company_id, case.baseline_version_id, case.current_version_id)


def _flag():
    if not get_settings().qualification_graph_enabled:
        raise GraphError('GRAPH_STRATEGY_DISABLED')


def graph_summary(run):
    source, _, _ = validate_snapshot(run.payload)
    if (source.notice_version_id != str(run.notice_version_id) or run.snapshot_sha256 != run.payload['snapshot_sha256']
            or run.contract_version != VERSION or run.status != graph_status(run.payload)):
        raise GraphError('GRAPH_RECORD_PAYLOAD_MISMATCH')
    return {'id': str(run.id), 'notice_id': source.notice_id, 'notice_version_id': str(run.notice_version_id),
            'contract_version': run.contract_version, 'status': run.status,
            'snapshot_sha256': run.snapshot_sha256, 'source_basis_sha256': run.source_basis_sha256,
            'created_at': run.created_at.isoformat(), 'relation_status': run.payload['composition']['status'],
            'clause_count': len(run.payload['decisions'])}


def _load_run(db, case, run_id):
    run = db.get(QualificationGraphRun, run_id)
    if run is None: raise GraphError('GRAPH_NOT_FOUND')
    if run.notice_version_id not in _allowed_version_ids(case): raise GraphError('GRAPH_CASE_VERSION_MISMATCH')
    version = db.get(BidNoticeVersion, run.notice_version_id)
    if version is None or version.notice_id != case.notice_id: raise GraphError('GRAPH_NOTICE_MISMATCH')
    if graph_summary(run)['notice_id'] != str(case.notice_id): raise GraphError('GRAPH_NOTICE_MISMATCH')
    return run


def list_graphs(db, *, case_id):
    with db.no_autoflush:
        case = _case(db, case_id)
        rows = db.scalars(select(QualificationGraphRun).where(QualificationGraphRun.notice_version_id.in_(_allowed_version_ids(case)))
            .order_by(QualificationGraphRun.created_at.desc(), QualificationGraphRun.id.desc()).limit(100)).all()
        return {'case_id': str(case.id), 'baseline_version_id': str(case.baseline_version_id) if case.baseline_version_id else None,
            'current_version_id': str(case.current_version_id), 'items': [graph_summary(r) for r in rows],
            'limit': 100, 'selection_policy': 'EXPLICIT_RUN_IDS', 'more_may_exist': len(rows) == 100}


def read_graph(db, *, case_id, run_id):
    with db.no_autoflush:
        case = _case(db, case_id); run = _load_run(db, case, run_id)
        return {**graph_summary(run), 'snapshot': run.payload}


def run_graph_analysis(db, *, case_id, version_role, extractor):
    _flag()
    if version_role not in {'baseline','current'}: raise GraphError('INVALID_VERSION_ROLE')
    with db.no_autoflush:
        case = _case(db, case_id); basis_case = _case_basis(case)
        vid = case.baseline_version_id if version_role == 'baseline' else case.current_version_id
        if vid is None: raise GraphError('BASELINE_VERSION_REQUIRED')
        version = db.get(BidNoticeVersion, vid)
        if version is None or version.notice_id != case.notice_id: raise GraphError('GRAPH_NOTICE_MISMATCH')
        number, nid = version.version_number, case.notice_id
        version = _load_notice_version(db, notice_id=nid, version_number=number)
        source = build_qualification_analysis_input(version).model_copy(deep=True)
        basis = source_basis(version, source)
        manifest = [{'id': str(d.id), 'name': d.name, 'source_field': d.source_field,
                     'status': d.extraction_status, 'file_sha256': d.file_sha256,
                     'text_sha256': d.extracted_text_sha256} for d in sorted(version.documents, key=lambda d: str(d.id))]
        snapshot = extract_document_graph(source, structured_extract=extractor, document_manifest=manifest,
                                           options=product_review_options())
        refreshed = _load_notice_version(db, notice_id=nid, version_number=number, refresh=True)
        db.refresh(case)
        if _case_basis(case) != basis_case or source_basis(refreshed, build_qualification_analysis_input(refreshed)) != basis:
            raise GraphError('GRAPH_SOURCE_CHANGED')
        run = QualificationGraphRun(notice_version_id=vid, contract_version=VERSION, status=graph_status(snapshot),
            source_basis_sha256=basis['source_sha256'], snapshot_sha256=snapshot['snapshot_sha256'], payload=snapshot)
        db.add(run); db.commit(); db.refresh(run)
        return {**graph_summary(run), 'snapshot': run.payload}


def judge_saved_graph(db, *, case_id, graph_run_id, reference_date):
    _flag()
    if not isinstance(reference_date, date) or isinstance(reference_date, datetime): raise GraphError('REFERENCE_DATE_REQUIRED')
    with db.no_autoflush:
        case = _case(db, case_id); basis_case = _case_basis(case)
        if case.company_id is None: raise GraphError('COMPANY_REQUIRED')
        run = _load_run(db, case, graph_run_id)
        version = db.get(BidNoticeVersion, run.notice_version_id)
        nid, version_number, source_sha = case.notice_id, version.version_number, run.source_basis_sha256
        latest = _load_notice_version(db, notice_id=nid, version_number=version_number, refresh=True)
        if source_basis(latest, build_qualification_analysis_input(latest))['source_sha256'] != source_sha:
            raise GraphError('GRAPH_SOURCE_CHANGED')
        company = _load_company(db, case.company_id)
        completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, case.company_id))
        profile = build_company_profile_snapshot(company, completeness).model_copy(deep=True)
        anchors = {}
        for name, value in [('NOTICE_DATE', latest.posted_at), ('SUBMISSION_DEADLINE', latest.bid_closed_at)]:
            if value is not None and value.tzinfo is not None:
                anchors[name] = value.astimezone(ZoneInfo('Asia/Seoul')).date()
        result = judge_document_graph(run.payload, profile, case_id=str(case.id), reference_date=reference_date, anchor_dates=anchors)
        result['rule_version'] = RULE_VERSION
        db.expire_all()
        db.refresh(case)
        if _case_basis(case) != basis_case: raise GraphError('GRAPH_JUDGMENT_BASIS_CHANGED')
        reread = _load_company(db, case.company_id)
        current_completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, case.company_id))
        latest = _load_notice_version(db, notice_id=nid, version_number=version_number, refresh=True)
        if (source_basis(latest, build_qualification_analysis_input(latest))['source_sha256'] != source_sha
                or fingerprint(build_company_profile_snapshot(reread, current_completeness).model_dump(mode='json')) != result['profile_sha256']):
            raise GraphError('GRAPH_JUDGMENT_BASIS_CHANGED')
        record = QualificationGraphJudgmentRun(preflight_case_id=case.id, graph_run_id=run.id, company_id=case.company_id,
            rule_version=RULE_VERSION, reference_date=reference_date, profile_snapshot=profile.model_dump(mode='json'),
            payload_sha256=fingerprint(result), payload=result)
        db.add(record); db.commit(); db.refresh(record)
        return {'id': str(record.id), 'graph_run_id': str(run.id), 'created_at': record.created_at.isoformat(), 'result': result}


def read_graph_judgment(db, *, case_id, judgment_id):
    with db.no_autoflush:
        case = _case(db, case_id)
        row = db.get(QualificationGraphJudgmentRun, judgment_id)
        if row is None: raise GraphError('GRAPH_JUDGMENT_NOT_FOUND')
        if row.preflight_case_id != case.id or row.company_id != case.company_id: raise GraphError('GRAPH_JUDGMENT_CASE_MISMATCH')
        run = _load_run(db, case, row.graph_run_id)
        if (row.payload_sha256 != fingerprint(row.payload) or row.payload['snapshot_sha256'] != run.snapshot_sha256
                or row.payload['profile_sha256'] != fingerprint(row.profile_snapshot)
                or row.payload['case_id'] != str(case.id) or row.payload['company_id'] != str(row.company_id)
                or row.payload['reference_date'] != row.reference_date.isoformat() or row.payload['rule_version'] != row.rule_version):
            raise GraphError('GRAPH_JUDGMENT_INTEGRITY')
        return {'id': str(row.id), 'graph_run_id': str(run.id), 'created_at': row.created_at.isoformat(), 'result': row.payload,
                'stored_basis_only': True}


def compare_saved_graphs(db, *, case_id, baseline_run_id, current_run_id):
    """모델 호출·DB 갱신 없이 지정된 두 저장 실행을 비교한다."""
    with db.no_autoflush:
        case = _case(db, case_id)
        baseline, current = _load_run(db, case, baseline_run_id), _load_run(db, case, current_run_id)
        if baseline.id == current.id: raise GraphError('DISTINCT_GRAPH_RUNS_REQUIRED')
        bversion, cversion = db.get(BidNoticeVersion, baseline.notice_version_id), db.get(BidNoticeVersion, current.notice_version_id)
        same_version = baseline.notice_version_id == current.notice_version_id
        if not same_version and (baseline.notice_version_id != case.baseline_version_id or current.notice_version_id != case.current_version_id
                                 or bversion.version_number >= cversion.version_number):
            raise GraphError('GRAPH_COMPARISON_DIRECTION_MISMATCH')
        result = compare_document_graphs(baseline.payload, current.payload)
        return {**result, 'case_id': str(case.id), 'baseline_run_id': str(baseline.id), 'current_run_id': str(current.id),
                'mode': 'REPEATED_ANALYSIS' if same_version else 'NOTICE_VERSION_COMPARISON',
                'comparison_basis': 'EXPLICIT_SAVED_SNAPSHOTS', 'db_writes': False}
