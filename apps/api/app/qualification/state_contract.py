"""분석 실행·검토 완전성·저장 판정·기준 유효성을 분리하는 읽기 계약.

최신 분석 우선/current-rule을 유지한다. 최근 실패를 과거 성공으로 덮지 않고,
판정을 계산하거나 원문 전체의 완전성을 인증하지 않는다. DB/LLM/현재시각 의존성 없음.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Any, Literal

STATE_VERSION = "qualification-state-v1"
CoverageState = Literal["UNVERIFIED", "COMPLETE", "INCOMPLETE", "INVALID", "EMPTY"]
OverallStatus = Literal["eligible", "ineligible", "insufficient_data"]


class StateInputError(ValueError):
    """고정 코드만 포함한다. 잘못된 자료를 미검토로 바꾸지 않는다."""


def payload_fingerprint(value: Any) -> str:
    """의미가 있을 수 있는 배열 순서와 알 수 없는 필드도 보존한다."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise StateInputError("NON_JSON_STATE_INPUT") from error
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StateInputError("INVALID_IDENTIFIER")


def _time(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StateInputError("TIMESTAMP_REQUIRES_TIMEZONE")


def _day(value: object) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise StateInputError("INVALID_REFERENCE_DATE")


def _unique(values: tuple[str, ...]) -> bool:
    return isinstance(values, tuple) and all(isinstance(x, str) and x.strip() for x in values) and len(set(values)) == len(values)


@dataclass(frozen=True)
class ReviewScope:
    case_id: str
    notice_id: str
    notice_version_id: str
    company_id: str | None
    rule_version: str

    def __post_init__(self) -> None:
        for value in (self.case_id, self.notice_id, self.notice_version_id, self.rule_version):
            _identifier(value)
        if self.company_id is not None:
            _identifier(self.company_id)


@dataclass(frozen=True)
class AnalysisSnapshot:
    id: str
    notice_version_id: str
    created_at: datetime
    status: str
    requirement_keys: tuple[str, ...] = ()
    coverage: CoverageState = "UNVERIFIED"
    integrity_valid: bool = True

    def __post_init__(self) -> None:
        _identifier(self.id)
        _identifier(self.notice_version_id)
        _time(self.created_at)
        if not isinstance(self.status, str) or self.status not in {"PENDING", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED"}:
            raise StateInputError("UNKNOWN_ANALYSIS_STATUS")
        if not isinstance(self.coverage, str) or self.coverage not in {"UNVERIFIED", "COMPLETE", "INCOMPLETE", "INVALID", "EMPTY"}:
            raise StateInputError("UNKNOWN_COVERAGE_STATUS")
        if not isinstance(self.integrity_valid, bool) or not isinstance(self.requirement_keys, tuple):
            raise StateInputError("INVALID_ANALYSIS_METADATA")


@dataclass(frozen=True)
class JudgmentSnapshot:
    id: str
    case_id: str
    company_id: str
    notice_version_id: str
    analysis_run_id: str
    created_at: datetime
    rule_version: str
    analysis_status: str
    reference_date: date
    profile_sha256: str
    overall_status: OverallStatus
    requirement_keys: tuple[str, ...]
    unknown_reasons: tuple[str, ...] = ()
    has_user_answers: bool = False
    integrity_valid: bool = True

    def __post_init__(self) -> None:
        for value in (self.id, self.case_id, self.company_id, self.notice_version_id,
                      self.analysis_run_id, self.rule_version, self.profile_sha256):
            _identifier(value)
        _time(self.created_at)
        _day(self.reference_date)
        if not isinstance(self.overall_status, str) or self.overall_status not in {"eligible", "ineligible", "insufficient_data"}:
            raise StateInputError("UNKNOWN_OVERALL_STATUS")
        if not isinstance(self.has_user_answers, bool) or not isinstance(self.integrity_valid, bool):
            raise StateInputError("INVALID_JUDGMENT_METADATA")
        if not isinstance(self.requirement_keys, tuple) or not isinstance(self.unknown_reasons, tuple):
            raise StateInputError("INVALID_JUDGMENT_METADATA")


@dataclass(frozen=True)
class QualificationState:
    scope: ReviewScope
    lookup_state: Literal["OK", "FAILED"] = "OK"
    execution_state: str = "NOT_RUN"
    coverage_state: CoverageState = "UNVERIFIED"
    judgment_state: str = "NOT_RUN"
    freshness_state: str = "UNAVAILABLE"
    display_state: str = "UNREVIEWED"
    analysis_run_id: str | None = None
    # 읽어온 저장 판정과 현재 선택 기준에 맞는 판정을 구분한다.
    observed_judgment_run_id: str | None = None
    selected_judgment_run_id: str | None = None
    stored_overall_status: OverallStatus | None = None
    stored_reference_date: date | None = None
    requested_reference_date: date | None = None
    profile_check: str = "NOT_CHECKED"
    reference_date_check: str = "NOT_REQUESTED"
    answer_basis_check: str = "NOT_CHECKED"
    reasons: tuple[str, ...] = ()
    unknown_reasons: tuple[str, ...] = ()
    full_notice_eligibility_asserted: bool = False
    contract_version: str = STATE_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for field in ("stored_reference_date", "requested_reference_date"):
            value[field] = value[field].isoformat() if value[field] is not None else None
        return {**value, "state_sha256": payload_fingerprint(value)}


def lookup_failed(scope: ReviewScope) -> QualificationState:
    return QualificationState(scope, lookup_state="FAILED", execution_state="UNKNOWN",
                              judgment_state="BLOCKED", display_state="LOAD_FAILED",
                              reasons=("STATE_LOOKUP_FAILED",))


def coverage_from_diagnostics(status: str, diagnostics: Sequence[object]) -> CoverageState:
    """review_v1 처리 기록만 읽는다. legacy SUCCEEDED를 COMPLETE로 추정하지 않는다."""
    audits = [d.get("details") for d in diagnostics
              if isinstance(d, Mapping) and d.get("code") == "REVIEW_EXECUTION_AUDIT"]
    if not audits:
        return "INCOMPLETE" if status in {"PARTIAL", "FAILED"} else "UNVERIFIED"
    if len(audits) != 1 or not isinstance(audits[0], Mapping):
        return "INVALID"
    audit = audits[0]
    coverage = audit.get("coverage")
    if not isinstance(coverage, Mapping):
        return "INVALID"
    state = coverage.get("coverage_status")
    total, processed = coverage.get("candidate_count"), coverage.get("processed_count")
    if (not isinstance(state, str) or state not in {"COMPLETE", "INCOMPLETE", "INVALID", "EMPTY"}
            or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (total, processed))
            or processed > total):
        return "INVALID"
    lists = ("missing_candidate_ids", "duplicate_candidate_ids", "unknown_candidate_ids",
             "invalid_response_indexes", "unresolved_candidate_ids", "needs_context_candidate_ids")
    if any(not isinstance(coverage.get(key), (list, tuple)) for key in lists):
        return "INVALID"
    if any(coverage[key] for key in lists[1:4]):
        return "INVALID"
    if state == "EMPTY":
        return "EMPTY" if total == processed == 0 and not any(coverage[key] for key in lists) else "INVALID"
    if state == "COMPLETE" and (total == 0 or processed != total or any(coverage[key] for key in lists)):
        return "INVALID"
    plan = audit.get("plan")
    if not isinstance(plan, Mapping):
        return "INVALID"
    if (audit.get("adapter_pending") or audit.get("invalid_candidate_ids") or plan.get("blocked")
            or plan.get("source_gaps")):
        return "INCOMPLETE" if state != "INVALID" else "INVALID"
    if status in {"PARTIAL", "FAILED"} and state == "COMPLETE":
        return "INCOMPLETE"
    return state


def select_qualification_state(
    scope: ReviewScope, analyses: Sequence[AnalysisSnapshot], judgments: Sequence[JudgmentSnapshot], *,
    current_profile_sha256: str | None, reference_date: date | None = None,
) -> QualificationState:
    """저장 스냅샷에서 기준에 맞는 결과를 선택한다. 유리한 결과로 fallback하지 않는다.

    날짜 미지정/사용자 답변 최신성 미검증은 CHECKS_INCOMPLETE다.
    쓰기 작업은 별도 경계에서 최신성과 권한을 다시 확인해야 한다.
    """
    if reference_date is not None:
        _day(reference_date)
    if current_profile_sha256 is not None:
        _identifier(current_profile_sha256)
    if any(not isinstance(x, AnalysisSnapshot) for x in analyses) or any(not isinstance(x, JudgmentSnapshot) for x in judgments):
        raise StateInputError("INVALID_SNAPSHOT_TYPE")
    available = [x for x in analyses if x.notice_version_id == scope.notice_version_id]
    owned = [x for x in judgments if x.case_id == scope.case_id and x.company_id == scope.company_id]
    if len({x.id for x in available}) != len(available):
        raise StateInputError("DUPLICATE_ANALYSIS_ID")
    if len({x.id for x in owned}) != len(owned):
        raise StateInputError("DUPLICATE_JUDGMENT_ID")
    state = QualificationState(scope, requested_reference_date=reference_date)
    if scope.company_id is None:
        return replace(state, display_state="PROFILE_REQUIRED", reasons=("COMPANY_PROFILE_REQUIRED",))
    if not available:
        return replace(state, reasons=("ANALYSIS_REQUIRED",))
    latest = max(available, key=lambda x: (x.created_at, x.id))
    execution = "RUNNING" if latest.status == "PENDING" else latest.status
    state = replace(state, analysis_run_id=latest.id, execution_state=execution, coverage_state=latest.coverage)
    if not latest.integrity_valid or not _unique(latest.requirement_keys):
        return replace(state, judgment_state="INVALID", display_state="DATA_INVALID", reasons=("ANALYSIS_INTEGRITY_ERROR",))
    if execution == "RUNNING":
        return replace(state, judgment_state="BLOCKED", display_state="ANALYSIS_RUNNING", reasons=("ANALYSIS_NOT_FINISHED",))
    if execution == "FAILED":
        return replace(state, judgment_state="BLOCKED", display_state="ANALYSIS_FAILED", reasons=("LATEST_ANALYSIS_FAILED",))
    if latest.coverage == "INVALID":
        return replace(state, judgment_state="INVALID", display_state="DATA_INVALID", reasons=("INVALID_REVIEW_COVERAGE",))
    if not latest.requirement_keys:
        return replace(state, judgment_state="BLOCKED", display_state="ANALYSIS_INCOMPLETE", reasons=("NO_CANONICAL_REQUIREMENTS",))
    candidates = [x for x in owned if x.notice_version_id == scope.notice_version_id
                  and x.analysis_run_id == latest.id and x.rule_version == scope.rule_version]
    if not candidates:
        reasons = []
        if owned:
            if not any(x.notice_version_id == scope.notice_version_id for x in owned):
                reasons.append("NOTICE_VERSION_CHANGED")
            if not any(x.analysis_run_id == latest.id for x in owned):
                reasons.append("ANALYSIS_CHANGED")
            if not any(x.rule_version == scope.rule_version for x in owned):
                reasons.append("RULE_VERSION_CHANGED")
            return replace(state, judgment_state="REJUDGMENT_REQUIRED", freshness_state="STALE",
                           display_state="REJUDGMENT_REQUIRED", reasons=tuple(reasons or ["CURRENT_BASIS_JUDGMENT_REQUIRED"]))
        return replace(state, display_state="JUDGMENT_REQUIRED", reasons=("JUDGMENT_REQUIRED",))
    selected = max(candidates, key=lambda x: (x.created_at, x.id))
    state = replace(state, observed_judgment_run_id=selected.id,
                    stored_overall_status=selected.overall_status, stored_reference_date=selected.reference_date)
    if (not selected.integrity_valid or selected.analysis_status != latest.status
            or not _unique(selected.requirement_keys) or set(selected.requirement_keys) != set(latest.requirement_keys)):
        return replace(state, judgment_state="INVALID", display_state="DATA_INVALID", reasons=("JUDGMENT_LINK_INTEGRITY_ERROR",))
    profile_check = ("NOT_CHECKED" if current_profile_sha256 is None else
                     "MATCH" if current_profile_sha256 == selected.profile_sha256 else "CHANGED")
    date_check = ("NOT_REQUESTED" if reference_date is None else
                  "MATCH" if reference_date == selected.reference_date else "CHANGED")
    answers = "UNVERIFIED" if selected.has_user_answers else "NOT_APPLICABLE"
    state = replace(state, profile_check=profile_check, reference_date_check=date_check, answer_basis_check=answers)
    stale = tuple(reason for failed, reason in ((profile_check == "CHANGED", "PROFILE_CHANGED"),
                  (date_check == "CHANGED", "REFERENCE_DATE_CHANGED")) if failed)
    if stale:
        return replace(state, judgment_state="REJUDGMENT_REQUIRED", freshness_state="STALE",
                       display_state="REJUDGMENT_REQUIRED", reasons=stale)
    checks_missing = profile_check != "MATCH" or date_check != "MATCH" or answers == "UNVERIFIED"
    reasons = []
    if profile_check == "NOT_CHECKED":
        reasons.append("PROFILE_FRESHNESS_UNVERIFIED")
    if date_check == "NOT_REQUESTED":
        reasons.append("REFERENCE_DATE_NOT_REQUESTED")
    if answers == "UNVERIFIED":
        reasons.append("ANSWER_FRESHNESS_UNVERIFIED")
    if latest.coverage == "UNVERIFIED":
        reasons.append("ANALYSIS_COMPLETENESS_UNVERIFIED")
    incomplete = latest.status == "PARTIAL" or latest.coverage in {"INCOMPLETE", "EMPTY"}
    if incomplete:
        reasons.append("ANALYSIS_INCOMPLETE")
    known = {"profile_missing", "requirement_uncertain", "evidence_missing"}
    unknown = tuple(sorted({x for x in selected.unknown_reasons if isinstance(x, str) and x in known}))
    return replace(state, judgment_state="AVAILABLE", selected_judgment_run_id=selected.id,
                   freshness_state="CHECKS_INCOMPLETE" if checks_missing else "CURRENT",
                   display_state="ANALYSIS_INCOMPLETE" if incomplete else "RESULT_AVAILABLE",
                   reasons=tuple(reasons), unknown_reasons=unknown)
