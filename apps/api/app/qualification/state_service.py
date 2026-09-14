"""현재 판정 상태의 읽기 전용 DB 어댑터. 분석/판정/commit을 실행하지 않는다.

호출자는 authorize_case_access를 먼저 수행해야 한다. no_autoflush는 호출자가
남겨둔 변경도 이 조회 때문에 flush되지 않게 한다. 쓰기 시점 검증은 별도다.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import CompanyQualificationProfileCompleteness, QualificationJudgmentRun
from ..models import PreflightCase
from .judgment import (QualificationJudgmentError, _load_company, _record_to_completeness,
                       build_company_profile_snapshot)
from .rules.judgment import RULE_VERSION
from .state_contract import (AnalysisSnapshot, JudgmentSnapshot, QualificationState, ReviewScope,
                             StateInputError, coverage_from_diagnostics, payload_fingerprint,
                             select_qualification_state)


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise StateInputError("INVALID_REFERENCE_LIST")
    return tuple(value)


def _analysis_snapshot(run) -> AnalysisSnapshot:
    diagnostics = run.diagnostics if run.diagnostics is not None else []
    if not isinstance(diagnostics, list):
        raise StateInputError("INVALID_ANALYSIS_DIAGNOSTICS")
    keys = tuple(item.requirement_key for item in run.requirements)
    evidence_keys = _string_list([item.evidence_key for item in run.evidence])
    refs = [key for item in run.requirements for key in _string_list(item.evidence_keys or [])]
    integrity = (run.contract_version == "ai-analysis-v0.2"
                 and run.analysis_kind == "QUALIFICATION_REQUIREMENTS"
                 and len(set(evidence_keys)) == len(evidence_keys)
                 and set(refs) <= set(evidence_keys)
                 and all(item.notice_version_id == str(run.notice_version_id) for item in run.evidence))
    coverage = coverage_from_diagnostics(run.status, diagnostics)
    if run.dropped_requirements and coverage != "INVALID":
        coverage = "INCOMPLETE"
    return AnalysisSnapshot(str(run.id), str(run.notice_version_id), run.created_at, run.status,
                            keys, coverage, integrity)


def _judgment_snapshot(run, analysis) -> JudgmentSnapshot:
    snapshot = run.profile_snapshot
    if not isinstance(snapshot, Mapping):
        raise StateInputError("INVALID_PROFILE_SNAPSHOT")
    valid = snapshot.get("company_id") == str(run.company_id)
    requirements = {item.requirement_key: set(_string_list(item.evidence_keys or []))
                    for item in analysis.requirements} if analysis is not None else {}
    keys = tuple(item.requirement_key for item in run.judgments)
    for item in run.judgments:
        valid = valid and item.status in {"SATISFIED", "UNSATISFIED", "UNKNOWN"}
        valid = valid and item.rule_version in (None, run.rule_version)
        valid = valid and (item.status != "UNKNOWN" or item.unknown_reason in
                           {"profile_missing", "requirement_uncertain", "evidence_missing"})
        valid = valid and set(_string_list(item.requirement_evidence_keys or [])) <= requirements.get(item.requirement_key, set())
    return JudgmentSnapshot(
        id=str(run.id), case_id=str(run.preflight_case_id), company_id=str(run.company_id),
        notice_version_id=str(run.notice_version_id), analysis_run_id=str(run.analysis_run_id),
        created_at=run.created_at, rule_version=run.rule_version, analysis_status=run.analysis_status,
        reference_date=run.reference_date, profile_sha256=payload_fingerprint(snapshot),
        overall_status=run.overall_status, requirement_keys=keys,
        unknown_reasons=tuple(item.unknown_reason for item in run.judgments
                              if item.status == "UNKNOWN" and item.unknown_reason),
        has_user_answers=any(item.basis_type == "USER_ANSWER" or item.value_source == "askback" for item in run.judgments),
        integrity_valid=valid,
    )


def read_qualification_state(db: Session, *, case_id: UUID,
                             reference_date: date | None = None) -> QualificationState:
    """최신 분석 + 현재 회사/차수/규칙 판정. 과거 성공으로 fallback하지 않는다.

    최신 과거 판정 1건은 재판정 사유 확인에만 사용한다. 전체 목록을 상위 N건으로
    잘라 탐색하지 않으며 새 분석/판정 레코드를 만들지 않는다.
    """
    with db.no_autoflush:
        case = db.get(PreflightCase, case_id)
        if case is None:
            raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "사전검토 건을 찾을 수 없습니다.", status_code=404)
        scope = ReviewScope(str(case.id), str(case.notice_id), str(case.current_version_id),
                            str(case.company_id) if case.company_id is not None else None, RULE_VERSION)
        if case.company_id is None:
            return select_qualification_state(scope, [], [], current_profile_sha256=None,
                                              reference_date=reference_date)
        analysis = db.scalar(select(QualificationAnalysisRun)
            .where(QualificationAnalysisRun.notice_version_id == case.current_version_id)
            .options(selectinload(QualificationAnalysisRun.requirements),
                     selectinload(QualificationAnalysisRun.evidence),
                     selectinload(QualificationAnalysisRun.notice_version))
            .order_by(QualificationAnalysisRun.created_at.desc(), QualificationAnalysisRun.id.desc()).limit(1))
        if analysis is None:
            return select_qualification_state(scope, [], [], current_profile_sha256=None,
                                              reference_date=reference_date)
        if analysis.notice_version.notice_id != case.notice_id:
            raise StateInputError("ANALYSIS_NOTICE_MISMATCH")
        analysis_snapshot = _analysis_snapshot(analysis)
        if analysis.status in {"PENDING", "RUNNING", "FAILED"} or not analysis_snapshot.requirement_keys:
            return select_qualification_state(scope, [analysis_snapshot], [], current_profile_sha256=None,
                                              reference_date=reference_date)
        base = select(QualificationJudgmentRun).where(
            QualificationJudgmentRun.preflight_case_id == case.id,
            QualificationJudgmentRun.company_id == case.company_id,
        ).options(selectinload(QualificationJudgmentRun.judgments))
        order = (QualificationJudgmentRun.created_at.desc(), QualificationJudgmentRun.id.desc())
        current = db.scalar(base.where(
            QualificationJudgmentRun.notice_version_id == case.current_version_id,
            QualificationJudgmentRun.analysis_run_id == analysis.id,
            QualificationJudgmentRun.rule_version == RULE_VERSION,
        ).order_by(*order).limit(1))
        historical = None if current is not None else db.scalar(base.order_by(*order).limit(1))
        runs = [item for item in (current, historical) if item is not None]
        current_hash = None
        if current is not None:
            company = _load_company(db, case.company_id)
            completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, case.company_id))
            profile = build_company_profile_snapshot(company, completeness)
            current_hash = payload_fingerprint(profile.model_dump(mode="json"))
        # 읽는 도중 최신 분석이 바뀌면 혼합된 관측을 현재 결과로 반환하지 않는다.
        # 전체 snapshot isolation/CAS나 쓰기 시점 재검증을 대체하지 않는다.
        latest_basis = db.execute(select(QualificationAnalysisRun.id, QualificationAnalysisRun.status)
            .where(QualificationAnalysisRun.notice_version_id == case.current_version_id)
            .order_by(QualificationAnalysisRun.created_at.desc(), QualificationAnalysisRun.id.desc()).limit(1)).first()
        if latest_basis is None or tuple(latest_basis) != (analysis.id, analysis.status):
            raise StateInputError("STATE_BASIS_CHANGED_DURING_READ")
        return select_qualification_state(scope, [analysis_snapshot],
            [_judgment_snapshot(item, analysis) for item in runs],
            current_profile_sha256=current_hash, reference_date=reference_date)
