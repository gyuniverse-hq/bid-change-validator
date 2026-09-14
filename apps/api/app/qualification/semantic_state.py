"""4-B 조항별 의미 분석에 상태 계약을 연결한다. 공고 전체 AND를 임의 생성하지 않는다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .state_contract import STATE_VERSION, StateInputError, payload_fingerprint

if TYPE_CHECKING:
    from ..ai.qualification.extraction.review_semantic_judgment import SemanticAnalysis


def describe_semantic_state(analysis: SemanticAnalysis) -> dict[str, Any]:
    """실행 결과와 판정 연결을 대조한다. 원문/회사 상세/모델 reason은 출력하지 않는다."""
    execution = analysis.execution
    coverage = execution.coverage
    targets = set(execution.plan.target_candidate_ids)
    decisions = tuple(execution.decisions)
    ids = [item.candidate_id for item in decisions]
    requirement_ids = {item.candidate_id for item in decisions if item.status == "REQUIREMENT"}
    judgments = tuple(analysis.judgments)
    judgment_ids = [item.candidate_id for item in judgments]
    if (len(ids) != len(set(ids)) or not set(ids) <= targets
            or len(judgment_ids) != len(set(judgment_ids)) or set(judgment_ids) != requirement_ids):
        raise StateInputError("SEMANTIC_RESULT_LINK_MISMATCH")
    if coverage.coverage_status not in {"COMPLETE", "INCOMPLETE", "INVALID", "EMPTY"}:
        raise StateInputError("UNKNOWN_SEMANTIC_COVERAGE_STATUS")
    if coverage.candidate_count != len(targets) or coverage.processed_count != len(ids):
        raise StateInputError("SEMANTIC_COVERAGE_COUNT_MISMATCH")
    if any(item.status not in {"SATISFIED", "UNSATISFIED", "UNKNOWN"} for item in judgments):
        raise StateInputError("UNKNOWN_CLAUSE_JUDGMENT")
    contexts = {item.context_sha256 for item in judgments}
    companies = {item.company_id for item in judgments}
    rules = {item.rule_version for item in judgments}
    if len(contexts) > 1 or len(companies) > 1 or len(rules) > 1:
        raise StateInputError("MIXED_SEMANTIC_JUDGMENT_CONTEXT")
    missing = targets - set(ids)
    invalid = bool(execution.invalid_candidate_ids) or coverage.coverage_status == "INVALID"
    pending = {item.candidate_id for item in decisions if item.status in {"UNRESOLVED", "NEEDS_CONTEXT"}
               or getattr(item, "pending_codes", ())}
    pending.update(item.candidate_id for item in judgments if item.pending_codes)
    if coverage.coverage_status == "COMPLETE" and (missing or invalid or
            any(item.status in {"UNRESOLVED", "NEEDS_CONTEXT"} for item in decisions)):
        raise StateInputError("CONTRADICTORY_SEMANTIC_COVERAGE")
    reasons = []
    if not targets:
        reasons.append("NO_REVIEW_CANDIDATES")
    if missing:
        reasons.append("UNPROCESSED_CANDIDATES")
    if invalid:
        reasons.append("INVALID_CANDIDATE_RESPONSES")
    if coverage.coverage_status == "INCOMPLETE":
        reasons.append("CANDIDATE_COVERAGE_INCOMPLETE")
    if pending:
        reasons.append("UNRESOLVED_CLAUSE_SEMANTICS")
    if execution.plan.blocked:
        reasons.append("REQUEST_TARGETS_BLOCKED")
    if execution.plan.inventory.source_gaps:
        reasons.append("SOURCE_RANGE_GAPS")
    if not requirement_ids:
        reasons.append("NO_REQUIREMENTS_VERIFIED")
    processing = "EMPTY" if not targets else "INVALID" if invalid else "INCOMPLETE" if missing else "COMPLETE"
    semantic_coverage = "INCOMPLETE" if reasons else "COMPLETE"
    clause_counts = {key: sum(item.status == key for item in judgments)
                     for key in ("SATISFIED", "UNSATISFIED", "UNKNOWN")}
    # 조항 처리 내역과 프로필 UNKNOWN을 섞지 않는다. 선호 조건 미달도 공고 미달이 아니다.
    state = {"contract_version": STATE_VERSION, "scope": "CLAUSE_SET",
        "notice_id": analysis.notice_id, "notice_version_id": analysis.notice_version_id,
        "processing_state": processing, "candidate_coverage": coverage.coverage_status,
        "semantic_coverage": semantic_coverage, "notice_scope_state": "UNVERIFIED",
        "candidate_count": len(targets), "processed_count": len(ids),
        "requirement_candidate_count": len(requirement_ids), "pending_candidate_count": len(pending),
        "clause_judgment_counts": clause_counts,
        "mandatory_clause_count": sum(item.role == "mandatory" for item in judgments),
        "judgment_state": "AVAILABLE" if judgments else "NOT_RUN",
        "context_sha256": next(iter(contexts), None), "rule_version": next(iter(rules), None),
        "company_id": next(iter(companies), None),
        "notice_overall_status": None, "full_notice_eligibility_asserted": False,
        "reasons": reasons + ["NOTICE_APPLICABILITY_NOT_VERIFIED"]}
    return {**state, "state_sha256": payload_fingerprint(state)}


@dataclass(frozen=True)
class SemanticStateResult:
    analysis: SemanticAnalysis
    state: dict[str, Any]


def analyze_semantics_with_state(*args, **kwargs) -> SemanticStateResult:
    """기존 4-B 명시적 진입점 결과에 상태를 부여한다. DB 저장 없음."""
    from ..ai.qualification.extraction.review_semantic_judgment import analyze_qualification_semantics
    analysis = analyze_qualification_semantics(*args, **kwargs)
    return SemanticStateResult(analysis, describe_semantic_state(analysis))
