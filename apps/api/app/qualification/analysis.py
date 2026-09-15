"""Backend service boundary for qualification Requirement analysis persistence."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..ai.qualification.extraction.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    StructuredExtractor,
    analyze_qualification_documents,
)
from ..ai.qualification.extraction.analysis_result import AnalysisDiagnostic, RequirementAnalysisResult
from ..config import get_settings
from .analysis_execution import (EXECUTION_CODE, EXECUTION_VERSION, SUPPORTED_STRATEGIES,
                                 execution_metadata, product_review_options, source_basis)
from ..ai.contracts import Evidence, EvidenceLocation, QualificationRequirement
from ..analysis_models import (
    QualificationAnalysisRun,
    QualificationEvidenceRecord,
    QualificationRequirementRecord,
)
from ..analysis_schemas import QualificationAnalysisRunRead, QualificationAnalysisRunSummary
from ..models import BidNoticeVersion, NoticeDocument


class QualificationAnalysisError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _load_notice_version(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
    refresh: bool = False,
) -> BidNoticeVersion:
    version = db.scalar(
        select(BidNoticeVersion)
        .where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
        )
        .options(selectinload(BidNoticeVersion.documents))
        .execution_options(populate_existing=refresh)
    )
    if version is None:
        raise QualificationAnalysisError(
            "NOTICE_VERSION_NOT_FOUND", "분석할 공고 버전을 찾을 수 없습니다."
        )
    return version


def build_qualification_analysis_input(version: BidNoticeVersion) -> QualificationAnalysisInput:
    documents = [
        QualificationDocumentInput(
            document_id=str(document.id),
            file_sha256=document.file_sha256,
            extracted_text_sha256=document.extracted_text_sha256,
            extracted_blocks=list(document.extracted_blocks or []),
        )
        for document in version.documents
        if document.extraction_status == "EXTRACTED" and document.extracted_blocks
    ]
    return QualificationAnalysisInput(
        notice_id=str(version.notice_id),
        notice_version_id=str(version.id),
        documents=documents,
    )


def _persist_result(
    db: Session,
    *,
    version: BidNoticeVersion,
    result: RequirementAnalysisResult,
) -> QualificationAnalysisRun:
    run = QualificationAnalysisRun(
        notice_version_id=version.id,
        contract_version=result.contract_version,
        analysis_kind=result.analysis_kind,
        status=result.status,
        target_chunk_ids=list(result.target_chunk_ids),
        diagnostics=[item.model_dump(mode="json") for item in result.diagnostics],
        dropped_requirements=[
            item.model_dump(mode="json") for item in result.dropped_requirements
        ],
    )
    db.add(run)
    db.flush()

    for requirement in result.requirements:
        db.add(
            QualificationRequirementRecord(
                analysis_run_id=run.id,
                requirement_key=requirement.requirement_key,
                requirement_group_key=requirement.requirement_group_key,
                group_operator=requirement.group_operator,
                type=requirement.type,
                operator=requirement.operator,
                value_json=requirement.value,
                unit=requirement.unit,
                period_months=(
                    Decimal(str(requirement.period_months))
                    if requirement.period_months is not None
                    else None
                ),
                scope=dict(requirement.scope),
                requirement_role=requirement.requirement_role,
                condition_complexity=requirement.condition_complexity,
                required=requirement.required,
                raw=requirement.raw,
                confidence=(
                    Decimal(str(requirement.confidence))
                    if requirement.confidence is not None
                    else None
                ),
                evidence_keys=list(requirement.evidence_keys),
            )
        )

    for evidence in result.evidence:
        db.add(
            QualificationEvidenceRecord(
                analysis_run_id=run.id,
                evidence_key=evidence.evidence_key,
                source_type=evidence.source_type,
                document_id=evidence.document_id,
                notice_version_id=evidence.notice_version_id,
                case_id=evidence.case_id,
                chunk_id=evidence.chunk_id,
                location=evidence.location.model_dump(mode="json"),
                quote=evidence.quote,
                source_sha256=evidence.source_sha256,
                extracted_text_sha256=evidence.extracted_text_sha256,
            )
        )

    db.commit()
    return load_qualification_analysis_run(db, run.id)


def run_qualification_analysis(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
    structured_extract: StructuredExtractor,
    extraction_strategy: str = "legacy",
) -> QualificationAnalysisRun:
    # HTTP 우회한 내부 호출에서도 알려지지 않은 경로/비활성 경로를 실행하지 않는다.
    if extraction_strategy not in SUPPORTED_STRATEGIES:
        raise QualificationAnalysisError("UNSUPPORTED_EXTRACTION_STRATEGY", "지원하지 않는 분석 경로입니다.")
    if extraction_strategy == "review_v1" and not get_settings().qualification_review_v1_enabled:
        raise QualificationAnalysisError("EXTRACTION_STRATEGY_DISABLED", "조항별 검토 경로가 이 서버에서 활성화되지 않았습니다.")
    version = _load_notice_version(db, notice_id=notice_id, version_number=version_number)
    analysis_input = build_qualification_analysis_input(version).model_copy(deep=True)
    basis = source_basis(version, analysis_input)
    # 첨부 행 순서에 따라 동일 원문 요청이 달라지지 않게 한다.
    analysis_input.documents.sort(key=lambda item: item.document_id)
    options = product_review_options() if extraction_strategy == "review_v1" else None
    kwargs = {"extraction_strategy": extraction_strategy, "review_options": options} if options else {}
    result = analyze_qualification_documents(analysis_input, structured_extract=structured_extract, **kwargs)
    diagnostics = list(result.diagnostics)
    status = result.status
    if extraction_strategy == "review_v1" and basis["omitted_document_ids"]:
        diagnostics.append(AnalysisDiagnostic(code="DOCUMENT_INPUT_INCOMPLETE", severity="WARNING",
            message="분석 입력에 포함되지 못한 첨부가 있습니다. 해당 문서의 조건까지 검토했다고 볼 수 없습니다.",
            details={"document_ids": basis["omitted_document_ids"]}))
        if status == "SUCCEEDED":
            status = "PARTIAL"
    # 모델 대기 중 원문/추출 상태가 바뀌면 옛 입력의 결과를 새 기준으로 저장하지 않는다.
    # 비교 직후 변경까지 잠그는 CAS/격리 수준 보증은 아니며, 동시 실행 기록은 모두 보존한다.
    version = _load_notice_version(db, notice_id=notice_id, version_number=version_number, refresh=True)
    latest_basis = source_basis(version, build_qualification_analysis_input(version))
    if basis["source_sha256"] != latest_basis["source_sha256"]:
        raise QualificationAnalysisError("ANALYSIS_SOURCE_CHANGED", "분석 중 원문 기준이 바뀌어 결과를 저장하지 않았습니다. 원문 상태를 다시 확인해 주세요.")
    diagnostics.append(AnalysisDiagnostic(code=EXECUTION_CODE, severity="INFO",
        message="분석 경로와 입력 기준 기록입니다. 추출 정확성이나 참가 가능을 보증하지 않습니다.",
        details={"version": EXECUTION_VERSION, "strategy": extraction_strategy, **basis,
                 "model": getattr(structured_extract, "model", None),
                 "max_calls": options.max_calls if options else None,
                 "max_retries": options.max_retries if options else None}))
    result = result.model_copy(update={"diagnostics": diagnostics, "status": status})
    return _persist_result(db, version=version, result=result)


def load_qualification_analysis_run(
    db: Session, run_id: UUID
) -> QualificationAnalysisRun:
    run = db.scalar(
        select(QualificationAnalysisRun)
        .where(QualificationAnalysisRun.id == run_id)
        .options(
            selectinload(QualificationAnalysisRun.notice_version),
            selectinload(QualificationAnalysisRun.requirements),
            selectinload(QualificationAnalysisRun.evidence),
        )
    )
    if run is None:
        raise QualificationAnalysisError(
            "ANALYSIS_RUN_NOT_FOUND", "자격요건 분석 실행을 찾을 수 없습니다."
        )
    return run


def analysis_run_response(run: QualificationAnalysisRun) -> QualificationAnalysisRunRead:
    version = run.notice_version
    requirements = [
        QualificationRequirement(
            requirement_key=item.requirement_key,
            requirement_group_key=item.requirement_group_key,
            group_operator=item.group_operator,
            notice_version_id=str(version.id),
            type=item.type,
            operator=item.operator,
            value=item.value_json,
            unit=item.unit,
            period_months=float(item.period_months) if item.period_months is not None else None,
            scope=dict(item.scope or {}),
            requirement_role=item.requirement_role,
            condition_complexity=item.condition_complexity,
            required=item.required,
            raw=item.raw,
            confidence=float(item.confidence) if item.confidence is not None else None,
            evidence_keys=list(item.evidence_keys or []),
        )
        for item in sorted(run.requirements, key=lambda value: value.requirement_key)
    ]
    evidence = [
        Evidence(
            evidence_key=item.evidence_key,
            source_type=item.source_type,
            document_id=item.document_id,
            notice_version_id=item.notice_version_id,
            case_id=item.case_id,
            chunk_id=item.chunk_id,
            location=EvidenceLocation(**dict(item.location or {})),
            quote=item.quote,
            source_sha256=item.source_sha256,
            extracted_text_sha256=item.extracted_text_sha256,
        )
        for item in sorted(run.evidence, key=lambda value: value.evidence_key)
    ]
    metadata = execution_metadata(run.diagnostics)
    return QualificationAnalysisRunRead(
        id=run.id,
        notice_id=version.notice_id,
        notice_version_id=version.id,
        version_number=version.version_number,
        contract_version=run.contract_version,
        analysis_kind=run.analysis_kind,
        status=run.status,
        target_chunk_ids=list(run.target_chunk_ids or []),
        diagnostics=list(run.diagnostics or []),
        dropped_requirements=list(run.dropped_requirements or []),
        requirements=requirements,
        evidence=evidence,
        created_at=run.created_at,
        extraction_strategy=metadata["strategy"] if metadata else None,
        execution_basis=metadata,
    )


def list_qualification_analysis_runs(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
) -> list[QualificationAnalysisRunSummary]:
    version = _load_notice_version(db, notice_id=notice_id, version_number=version_number)
    runs = db.scalars(
        select(QualificationAnalysisRun)
        .where(QualificationAnalysisRun.notice_version_id == version.id)
        .options(
            selectinload(QualificationAnalysisRun.requirements),
            selectinload(QualificationAnalysisRun.evidence),
        )
        .order_by(QualificationAnalysisRun.created_at.desc())
    ).all()
    return [
        QualificationAnalysisRunSummary(
            id=run.id,
            notice_version_id=version.id,
            version_number=version.version_number,
            contract_version=run.contract_version,
            status=run.status,
            requirement_count=len(run.requirements),
            evidence_count=len(run.evidence),
            created_at=run.created_at,
        )
        for run in runs
    ]
