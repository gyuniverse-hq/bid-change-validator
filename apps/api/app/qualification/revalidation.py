"""Changed-notice Requirement diff and affected-only qualification revalidation."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.contracts import Judgment
from .rules.judgment import RULE_VERSION, derive_overall_status, judge_requirement
from .rules.requirement_diff import RequirementChange, diff_requirements
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import CompanyQualificationProfileCompleteness, QualificationJudgmentRecord, QualificationJudgmentRun
from ..models import PreflightCase
from .analysis import analysis_run_response
from .judgment import (
    load_judgment_analysis,
    QualificationJudgmentError,
    _load_company,
    _record_to_completeness,
    build_company_profile_snapshot,
    judgment_run_response,
    load_qualification_judgment_run,
)
from ..revalidation_models import QualificationRevalidationRun
from ..revalidation_schemas import QualificationRevalidationCreate, QualificationRevalidationRead


def _load_case(db: Session, case_id: UUID) -> PreflightCase:
    case = db.scalar(select(PreflightCase).where(PreflightCase.id == case_id).with_for_update())
    if case is None:
        raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "사전검토 건을 찾을 수 없습니다.", status_code=404)
    if case.baseline_version_id is None:
        raise QualificationJudgmentError("BASELINE_VERSION_REQUIRED", "변경공고 재검증을 위해 기준 공고 버전이 필요합니다.", status_code=422)
    if case.company_id is None:
        raise QualificationJudgmentError("COMPANY_PROFILE_REQUIRED", "변경공고 재검증을 위해 회사 프로필이 필요합니다.", status_code=422)
    return case


def _select_analysis_run(db: Session, *, notice_version_id: UUID, explicit_run_id: UUID | None, label: str) -> QualificationAnalysisRun:
    if explicit_run_id is not None:
        run = load_judgment_analysis(db, explicit_run_id)
    else:
        run_id = db.scalar(select(QualificationAnalysisRun.id).where(QualificationAnalysisRun.notice_version_id == notice_version_id).order_by(QualificationAnalysisRun.created_at.desc()).limit(1))
        if run_id is None:
            raise QualificationJudgmentError("QUALIFICATION_ANALYSIS_REQUIRED", f"{label} 공고 버전의 자격요건 분석 결과가 필요합니다.")
        run = load_judgment_analysis(db, run_id)
    if run.notice_version_id != notice_version_id:
        raise QualificationJudgmentError("ANALYSIS_VERSION_MISMATCH", f"선택한 {label} 분석 결과의 공고 버전이 일치하지 않습니다.", status_code=422)
    if run.status == "FAILED":
        raise QualificationJudgmentError("QUALIFICATION_ANALYSIS_FAILED", f"실패한 {label} 자격요건 분석 결과로는 재검증할 수 없습니다.")
    return run


def _copy_judgment(record: QualificationJudgmentRecord, *, notice_version_id: UUID, case_id: UUID, requirement_key: str, current_evidence_keys: list[str]) -> Judgment:
    return Judgment(
        judgment_key=f"JUDG:{case_id}:{requirement_key}", preflight_case_id=str(case_id), notice_version_id=str(notice_version_id), requirement_key=requirement_key,
        status=record.status, basis_type=record.basis_type, evidence_held=record.evidence_held,
        value_source=record.value_source, evidence_status=record.evidence_status,
        reason_code=record.reason_code, unknown_reason=record.unknown_reason,
        requires_evidence=record.requires_evidence, profile_refs=list(record.profile_refs or []), requirement_evidence_keys=list(current_evidence_keys), rule_version=record.rule_version,
    )


def reusable_current_answers(run, *, case, analysis, profile, reference_date):
    """Keep explicit current-version answers only on the exact unchanged basis.

    A baseline answer never proves a changed clause. A current answer already
    accepted against this same analysis/profile remains valid on revalidation.
    """
    if (run is None or run.preflight_case_id != case.id or run.company_id != case.company_id
            or run.notice_version_id != case.current_version_id or run.analysis_run_id != analysis.id
            or run.analysis_status != analysis.status or run.rule_version != RULE_VERSION
            or run.reference_date != reference_date or run.profile_snapshot != profile.model_dump(mode='json')):
        return {}
    return {j.requirement_key:j for j in run.judgments
            if j.basis_type=='USER_ANSWER' and j.value_source=='askback' and j.status in {'SATISFIED','UNSATISFIED'}}


def latest_qualification_revalidation(db: Session, *, case_id: UUID) -> QualificationRevalidationRead | None:
    """Read saved lineage only; never re-execute a mutation during recovery."""
    lineage = db.scalar(select(QualificationRevalidationRun).where(
        QualificationRevalidationRun.preflight_case_id == case_id
    ).order_by(QualificationRevalidationRun.created_at.desc(), QualificationRevalidationRun.id.desc()).limit(1))
    if lineage is None:
        return None
    result = judgment_run_response(load_qualification_judgment_run(db, lineage.result_judgment_run_id))
    return QualificationRevalidationRead(
        **{name: getattr(lineage, name) for name in QualificationRevalidationRead.model_fields if name != "result"},
        result=result,
    )


def run_qualification_revalidation(db: Session, *, case_id: UUID, payload: QualificationRevalidationCreate) -> QualificationRevalidationRead:
    case = _load_case(db, case_id)
    source = load_qualification_judgment_run(db, payload.source_judgment_run_id)
    if source.preflight_case_id != case.id:
        raise QualificationJudgmentError("JUDGMENT_CASE_MISMATCH", "기준 판정 실행과 사전검토 건이 일치하지 않습니다.", status_code=422)
    if source.company_id != case.company_id:
        raise QualificationJudgmentError("JUDGMENT_COMPANY_MISMATCH", "기준 판정의 회사와 현재 사전검토 회사가 일치하지 않습니다.", status_code=422)
    if source.notice_version_id != case.baseline_version_id:
        raise QualificationJudgmentError("SOURCE_JUDGMENT_NOT_BASELINE", "기준 판정은 사전검토 건의 baseline 공고 버전에 대한 결과여야 합니다.", status_code=422)
    if payload.baseline_analysis_run_id is not None and payload.baseline_analysis_run_id != source.analysis_run_id:
        raise QualificationJudgmentError("SOURCE_ANALYSIS_MISMATCH", "기준 분석은 기준 판정을 생성한 분석과 같아야 합니다.", status_code=422)
    if payload.reference_date is not None and payload.reference_date != source.reference_date:
        raise QualificationJudgmentError("REFERENCE_DATE_CHANGED_FULL_REJUDGMENT_REQUIRED", "판정 기준일이 달라 전체 재판정이 필요합니다.", status_code=409)
    if source.rule_version != RULE_VERSION:
        raise QualificationJudgmentError("RULE_CHANGED_FULL_REJUDGMENT_REQUIRED", "판정 규칙이 바뀌었습니다. 참가자격 화면에서 기준·현재 차수를 다시 판정한 뒤 재검증해 주세요.", status_code=409)
    latest_source = db.scalar(select(QualificationJudgmentRun.id).where(QualificationJudgmentRun.preflight_case_id == case_id, QualificationJudgmentRun.notice_version_id == case.baseline_version_id).order_by(QualificationJudgmentRun.created_at.desc()).limit(1))
    if latest_source != source.id:
        raise QualificationJudgmentError("STALE_JUDGMENT", "최신 기준 판정으로 재검증해 주세요.", status_code=409)

    baseline_analysis = _select_analysis_run(db, notice_version_id=case.baseline_version_id, explicit_run_id=payload.baseline_analysis_run_id or source.analysis_run_id, label="기준")
    current_analysis = _select_analysis_run(db, notice_version_id=case.current_version_id, explicit_run_id=payload.current_analysis_run_id, label="현재")
    from .source_repair import source_conditions
    from .rules.source_contracts import VERSION
    snapshot, conditions = source_conditions(current_analysis.notice_version)
    marker = {'version': VERSION, 'fingerprint': snapshot.fingerprint}
    if conditions and not any(d.get('code') == 'SOURCE_CONTRACTS_APPLIED' and d.get('details', {}).get('source') == marker
                              for d in current_analysis.diagnostics or []):
        raise QualificationJudgmentError('SOURCE_CONTRACT_REVIEW_REQUIRED',
            '현재 차수의 원문 조건 보완이 필요합니다. 참가자격 화면에서 저장된 분석으로 다시 판정한 뒤 재검증해 주세요.')
    baseline = analysis_run_response(baseline_analysis)
    current = analysis_run_response(current_analysis)
    changes = diff_requirements(baseline.requirements, current.requirements)

    company = _load_company(db, case.company_id)
    completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, company.id))
    current_profile = build_company_profile_snapshot(company, completeness)
    if current_profile.model_dump(mode="json") != dict(source.profile_snapshot or {}):
        raise QualificationJudgmentError(
            "PROFILE_CHANGED_FULL_REJUDGMENT_REQUIRED",
            "기준 판정 이후 회사 프로필이 변경되어 affected-only 재검증을 사용할 수 없습니다. 전체 자격판정을 다시 실행하세요.",
        )

    source_by_key = {item.requirement_key: item for item in source.judgments}
    change_by_current = {item.current_key: item for item in changes if item.current_key is not None}
    reference_date = payload.reference_date or source.reference_date or date.today()
    current_run = db.scalar(select(QualificationJudgmentRun).where(
        QualificationJudgmentRun.preflight_case_id == case_id,
        QualificationJudgmentRun.notice_version_id == case.current_version_id,
    ).order_by(QualificationJudgmentRun.created_at.desc(),QualificationJudgmentRun.id.desc()).limit(1))
    current_answers = reusable_current_answers(current_run,case=case,analysis=current_analysis,
                                               profile=current_profile,reference_date=reference_date)
    judgments: list[Judgment] = []
    revalidated_keys: list[str] = []

    for requirement in current.requirements:
        change = change_by_current.get(requirement.requirement_key)
        if change is not None and change.change_type == "UNCHANGED" and change.baseline_key:
            source_record = source_by_key.get(change.baseline_key)
            if source_record is not None:
                judgments.append(_copy_judgment(
                    source_record,
                    notice_version_id=case.current_version_id,
                    case_id=case.id,
                    requirement_key=requirement.requirement_key,
                    current_evidence_keys=list(requirement.evidence_keys),
                ))
                continue
        judgment = judge_requirement(requirement, current_profile, preflight_case_id=str(case.id), reference_date=reference_date)
        from .rules.source_contracts import valid_contract
        saved = current_answers.get(requirement.requirement_key)
        if judgment.status == 'UNKNOWN' and saved is not None and valid_contract(requirement):
            judgment = _copy_judgment(saved,notice_version_id=case.current_version_id,case_id=case.id,
                requirement_key=requirement.requirement_key,current_evidence_keys=list(requirement.evidence_keys))
        judgments.append(judgment)
        revalidated_keys.append(requirement.requirement_key)

    overall_status = derive_overall_status(current.requirements, judgments, analysis_status=current_analysis.status)

    result_run = QualificationJudgmentRun(
        preflight_case_id=case.id, analysis_run_id=current_analysis.id, company_id=case.company_id, notice_version_id=case.current_version_id,
        overall_status=overall_status, rule_version=source.rule_version, reference_date=reference_date,
        profile_snapshot=current_profile.model_dump(mode="json"), analysis_status=current_analysis.status,
    )
    db.add(result_run); db.flush()
    for item in judgments:
        db.add(QualificationJudgmentRecord(
            judgment_run_id=result_run.id, judgment_key=item.judgment_key, requirement_key=item.requirement_key,
            status=item.status, basis_type=item.basis_type, evidence_held=item.evidence_held,
            value_source=item.value_source, evidence_status=item.evidence_status,
            reason_code=item.reason_code, unknown_reason=item.unknown_reason,
            requires_evidence=item.requires_evidence, profile_refs=list(item.profile_refs), requirement_evidence_keys=list(item.requirement_evidence_keys), rule_version=item.rule_version,
        ))

    lineage = QualificationRevalidationRun(
        preflight_case_id=case.id, source_judgment_run_id=source.id, result_judgment_run_id=result_run.id,
        baseline_analysis_run_id=baseline_analysis.id, current_analysis_run_id=current_analysis.id,
        changes=[item.model_dump(mode="json") for item in changes], revalidated_keys=revalidated_keys,
    )
    db.add(lineage); db.commit(); db.refresh(lineage)
    result = judgment_run_response(load_qualification_judgment_run(db, result_run.id))
    return QualificationRevalidationRead(
        id=lineage.id, preflight_case_id=lineage.preflight_case_id, source_judgment_run_id=lineage.source_judgment_run_id,
        result_judgment_run_id=lineage.result_judgment_run_id, baseline_analysis_run_id=lineage.baseline_analysis_run_id,
        current_analysis_run_id=lineage.current_analysis_run_id,
        changes=[RequirementChange.model_validate(item) for item in lineage.changes], revalidated_keys=list(lineage.revalidated_keys or []), created_at=lineage.created_at, result=result,
    )
