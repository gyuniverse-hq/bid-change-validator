"""Backend service boundary for qualification Requirement analysis persistence."""
from __future__ import annotations
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..ai.qualification.extraction.analysis_pipeline import QualificationAnalysisInput, QualificationDocumentInput, StructuredExtractor, analyze_qualification_documents
from ..ai.qualification.extraction.analysis_result import AnalysisDiagnostic, RequirementAnalysisResult
from ..config import get_settings
from .analysis_execution import EXECUTION_CODE, EXECUTION_VERSION, SUPPORTED_STRATEGIES, execution_metadata, product_review_options, source_basis
from ..ai.contracts import Evidence, EvidenceLocation, QualificationRequirement
from ..analysis_models import QualificationAnalysisRun, QualificationEvidenceRecord, QualificationRequirementRecord
from ..analysis_schemas import QualificationAnalysisRunRead, QualificationAnalysisRunSummary
from ..models import BidNoticeVersion, NoticeDocument


class QualificationAnalysisError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


def _load_notice_version(db: Session, *, notice_id: UUID, version_number: int, refresh: bool = False) -> BidNoticeVersion:
    version = db.scalar(select(BidNoticeVersion).where(BidNoticeVersion.notice_id == notice_id,
        BidNoticeVersion.version_number == version_number).options(selectinload(BidNoticeVersion.documents))
        .execution_options(populate_existing=refresh))
    if version is None:
        raise QualificationAnalysisError("NOTICE_VERSION_NOT_FOUND", "분석할 공고 버전을 찾을 수 없습니다.")
    return version


def build_qualification_analysis_input(version: BidNoticeVersion) -> QualificationAnalysisInput:
    documents = [QualificationDocumentInput(document_id=str(doc.id), file_sha256=doc.file_sha256,
        extracted_text_sha256=doc.extracted_text_sha256, extracted_blocks=list(doc.extracted_blocks or []))
        for doc in version.documents if doc.extraction_status == "EXTRACTED" and doc.extracted_blocks]
    return QualificationAnalysisInput(notice_id=str(version.notice_id), notice_version_id=str(version.id), documents=documents)


def _persist_result(db: Session, *, version: BidNoticeVersion, result: RequirementAnalysisResult) -> QualificationAnalysisRun:
    run = QualificationAnalysisRun(notice_version_id=version.id, contract_version=result.contract_version,
        analysis_kind=result.analysis_kind, status=result.status, target_chunk_ids=list(result.target_chunk_ids),
        diagnostics=[d.model_dump(mode="json") for d in result.diagnostics],
        dropped_requirements=[d.model_dump(mode="json") for d in result.dropped_requirements])
    db.add(run)
    db.flush()
    for req in result.requirements:
        db.add(QualificationRequirementRecord(analysis_run_id=run.id, requirement_key=req.requirement_key,
            requirement_group_key=req.requirement_group_key, group_operator=req.group_operator, type=req.type,
            operator=req.operator, value_json=req.value, unit=req.unit,
            period_months=Decimal(str(req.period_months)) if req.period_months is not None else None,
            scope=dict(req.scope), requirement_role=req.requirement_role, condition_complexity=req.condition_complexity,
            required=req.required, raw=req.raw, confidence=Decimal(str(req.confidence)) if req.confidence is not None else None,
            evidence_keys=list(req.evidence_keys)))
    for ev in result.evidence:
        db.add(QualificationEvidenceRecord(analysis_run_id=run.id, evidence_key=ev.evidence_key,
            source_type=ev.source_type, document_id=ev.document_id, notice_version_id=ev.notice_version_id,
            case_id=ev.case_id, chunk_id=ev.chunk_id, location=ev.location.model_dump(mode="json"), quote=ev.quote,
            source_sha256=ev.source_sha256, extracted_text_sha256=ev.extracted_text_sha256))
    db.commit()
    return load_qualification_analysis_run(db, run.id)


def run_qualification_analysis(db: Session, *, notice_id: UUID, version_number: int,
    structured_extract: StructuredExtractor, extraction_strategy: str = "legacy") -> QualificationAnalysisRun:
    if extraction_strategy not in SUPPORTED_STRATEGIES:
        raise QualificationAnalysisError("UNSUPPORTED_EXTRACTION_STRATEGY", "지원하지 않는 분석 경로입니다.")
    if extraction_strategy == "review_v1" and not get_settings().qualification_review_v1_enabled:
        raise QualificationAnalysisError("EXTRACTION_STRATEGY_DISABLED", "조항별 검토 경로가 이 서버에서 활성화되지 않았습니다.")
    version = _load_notice_version(db, notice_id=notice_id, version_number=version_number)
    analysis_input = build_qualification_analysis_input(version).model_copy(deep=True)
    basis = source_basis(version, analysis_input)
    analysis_input.documents.sort(key=lambda doc: doc.document_id)
    options = product_review_options() if extraction_strategy == "review_v1" else None
    kwargs = {"extraction_strategy": extraction_strategy, "review_options": options} if options else {}
    result = analyze_qualification_documents(analysis_input, structured_extract=structured_extract, **kwargs)
    diagnostics, status = list(result.diagnostics), result.status
    if extraction_strategy == "review_v1" and basis["omitted_document_ids"]:
        diagnostics.append(AnalysisDiagnostic(code="DOCUMENT_INPUT_INCOMPLETE", severity="WARNING",
            message="분석 입력에 포함되지 못한 첨부가 있습니다. 해당 문서의 조건까지 검토했다고 볼 수 없습니다.",
            details={"document_ids": basis["omitted_document_ids"]}))
        if status == "SUCCEEDED":
            status = "PARTIAL"
    # 관측 전후 비교이며 완전한 CAS/직렬화 격리 보장은 아니다.
    version = _load_notice_version(db, notice_id=notice_id, version_number=version_number, refresh=True)
    latest_basis = source_basis(version, build_qualification_analysis_input(version))
    if basis["source_sha256"] != latest_basis["source_sha256"]:
        raise QualificationAnalysisError("ANALYSIS_SOURCE_CHANGED", "분석 중 원문 기준이 바뀌어 결과를 저장하지 않았습니다. 원문 상태를 다시 확인해 주세요.")
    diagnostics.append(AnalysisDiagnostic(code=EXECUTION_CODE, severity="INFO",
        message="분석 경로와 입력 기준 기록입니다. 추출 정확성이나 참가 가능을 보증하지 않습니다.",
        details={"version": EXECUTION_VERSION, "strategy": extraction_strategy, **basis,
            "slot_pipeline_version": "qualification-slot-pipeline-v2", "model": getattr(structured_extract, "model", None),
            "max_calls": options.max_calls if options else None, "max_retries": options.max_retries if options else None}))
    result = result.model_copy(update={"diagnostics": diagnostics, "status": status})
    return _persist_result(db, version=version, result=result)


def load_qualification_analysis_run(db: Session, run_id: UUID) -> QualificationAnalysisRun:
    run = db.scalar(select(QualificationAnalysisRun).where(QualificationAnalysisRun.id == run_id).options(
        selectinload(QualificationAnalysisRun.notice_version), selectinload(QualificationAnalysisRun.requirements),
        selectinload(QualificationAnalysisRun.evidence)))
    if run is None:
        raise QualificationAnalysisError("ANALYSIS_RUN_NOT_FOUND", "자격요건 분석 실행을 찾을 수 없습니다.")
    return run


def analysis_run_response(run: QualificationAnalysisRun) -> QualificationAnalysisRunRead:
    version = run.notice_version
    requirements = [QualificationRequirement(requirement_key=item.requirement_key,
        requirement_group_key=item.requirement_group_key, group_operator=item.group_operator,
        notice_version_id=str(version.id), type=item.type, operator=item.operator, value=item.value_json, unit=item.unit,
        period_months=float(item.period_months) if item.period_months is not None else None, scope=dict(item.scope or {}),
        requirement_role=item.requirement_role, condition_complexity=item.condition_complexity, required=item.required,
        raw=item.raw, confidence=float(item.confidence) if item.confidence is not None else None,
        evidence_keys=list(item.evidence_keys or [])) for item in sorted(run.requirements, key=lambda v: v.requirement_key)]
    evidence = [Evidence(evidence_key=item.evidence_key, source_type=item.source_type, document_id=item.document_id,
        notice_version_id=item.notice_version_id, case_id=item.case_id, chunk_id=item.chunk_id,
        location=EvidenceLocation(**dict(item.location or {})), quote=item.quote, source_sha256=item.source_sha256,
        extracted_text_sha256=item.extracted_text_sha256) for item in sorted(run.evidence, key=lambda v: v.evidence_key)]
    metadata = execution_metadata(run.diagnostics)
    return QualificationAnalysisRunRead(id=run.id, notice_id=version.notice_id, notice_version_id=version.id,
        version_number=version.version_number, contract_version=run.contract_version, analysis_kind=run.analysis_kind,
        status=run.status, target_chunk_ids=list(run.target_chunk_ids or []), diagnostics=list(run.diagnostics or []),
        dropped_requirements=list(run.dropped_requirements or []), requirements=requirements, evidence=evidence,
        created_at=run.created_at, extraction_strategy=metadata["strategy"] if metadata else None, execution_basis=metadata)


def list_qualification_analysis_runs(db: Session, *, notice_id: UUID, version_number: int) -> list[QualificationAnalysisRunSummary]:
    version = _load_notice_version(db, notice_id=notice_id, version_number=version_number)
    runs = db.scalars(select(QualificationAnalysisRun).where(QualificationAnalysisRun.notice_version_id == version.id)
        .options(selectinload(QualificationAnalysisRun.requirements), selectinload(QualificationAnalysisRun.evidence))
        .order_by(QualificationAnalysisRun.created_at.desc())).all()
    return [QualificationAnalysisRunSummary(id=run.id, notice_version_id=version.id, version_number=version.version_number,
        contract_version=run.contract_version, status=run.status, requirement_count=len(run.requirements),
        evidence_count=len(run.evidence), created_at=run.created_at) for run in runs]
