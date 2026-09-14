"""review_graph_v1 → 기존 원자 판정기 → 원래 논리 그래프의 판정.

새 scope를 기존 판정기에 그대로 보내 무시되게 하지 않는다. 지원하는 scope만
명시적으로 변환한다. HTTP 저장/현재 분석 선택/공고 전체 참가 판정은 하지 않는다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, TYPE_CHECKING

from .review_conditions import (AtomicCondition, ConditionGraph, ConditionNode, count_matching_records,
                                deduplicate_atoms, evaluate_condition_graph, semantic_fingerprint)
from .review_execution import ReviewExecution, ReviewOptions, StructuredExtractor, _json, _sha, execute_review_plan
from .review_plan import build_review_inventory, plan_review_requests
from .review_semantics import SEMANTIC_VERSION, CompiledAtom, SemanticDecision, semantic_response_contract

if TYPE_CHECKING:
    from ....qualification.rules.judgment import CompanyProfileSnapshot
    from .analysis_pipeline import QualificationAnalysisInput


@dataclass(frozen=True)
class RecordObservation:
    """Backend/검증 자료가 제공한 실적별 추가 사실. LLM 출력은 이 객체로 받지 않는다.

    operation_months는 날짜 차이로 추정한 기간이 아니라 확인한 운영기간이다.
    basis_id는 추적 식별자이며 증빙의 진위/공적 인증을 보증하는 값은 아니다.
    """
    record_ref: str
    basis_id: str
    operation_months: int | None = None
    daily_meals: int | None = None
    amount_tax_basis: str = "UNSPECIFIED"

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.record_ref, self.basis_id)):
            raise ValueError("record_ref and basis_id are required")
        for value in (self.operation_months, self.daily_meals):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError("record measurements must be non-negative integers")
        if self.amount_tax_basis not in ("UNSPECIFIED", "INCLUDED", "EXCLUDED"):
            raise ValueError("unknown amount tax basis")


@dataclass(frozen=True)
class AtomEvaluation:
    atom_id: str
    status: str
    reason_code: str
    profile_refs_json: str = "[]"


@dataclass(frozen=True)
class SemanticJudgment:
    candidate_id: str
    company_id: str
    role: str
    status: str
    semantic_sha256: str | None
    context_sha256: str
    rule_version: str
    atoms: tuple[AtomEvaluation, ...]
    pending_codes: tuple[str, ...]


def _date(value: object) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("an explicit date is required")
    return value


def _compare(observed: int | None, operator: str, expected: int) -> str:
    if observed is None:
        return "UNKNOWN"
    operations = {">=": observed >= expected, ">": observed > expected,
                  "<=": observed <= expected, "<": observed < expected, "=": observed == expected}
    if operator not in operations:
        return "UNKNOWN"
    return "SATISFIED" if operations[operator] else "UNSATISFIED"


def _all(statuses: list[str]) -> str:
    return "UNSATISFIED" if "UNSATISFIED" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "SATISFIED"


def _validated_context(profile: CompanyProfileSnapshot, preflight_case_id: str,
                       reference_date: date, anchor_dates: Mapping[str, date] | None,
                       record_observations: Iterable[RecordObservation]):
    """회사/기준일 오류는 모델 호출 전에 확인한다."""
    from ....qualification.rules import judgment as rules

    _date(reference_date)
    if not isinstance(profile, rules.CompanyProfileSnapshot):
        raise ValueError("profile must be a CompanyProfileSnapshot")
    if not isinstance(preflight_case_id, str) or not preflight_case_id.strip():
        raise ValueError("preflight_case_id is required")
    dates = dict(anchor_dates or {})
    if set(dates) - {"NOTICE_DATE", "SUBMISSION_DEADLINE", "CONTRACT_START"}:
        raise ValueError("unknown date anchor")
    for value in dates.values():
        _date(value)
    rows = list(record_observations)
    if any(not isinstance(row, RecordObservation) for row in rows):
        raise ValueError("record observations must be typed facts")
    observations = {row.record_ref: row for row in rows}
    known_refs = [item.ref for item in profile.performances]
    if len(observations) != len(rows) or len(known_refs) != len(set(known_refs)):
        raise ValueError("duplicate record identity")
    if not set(observations) <= set(known_refs):
        raise ValueError("observation does not belong to the profile")
    return dates, tuple(rows), observations


def judge_semantic_decision(decision: SemanticDecision, profile: CompanyProfileSnapshot, *,
                            preflight_case_id: str, reference_date: date,
                            anchor_dates: Mapping[str, date] | None = None,
                            record_observations: Iterable[RecordObservation] = ()) -> SemanticJudgment:
    """실제 기존 judge_requirement를 호출한다. 그래프를 평탄한 ALL_OF로 보내지 않는다.

    결과는 이 조항의 조건 충족 여부다. 조항 간 부모 관계를 가정해 공고 전체 참가 여부를
    만들지 않는다. 불완전한 scope/주체는 원자 일부의 미달로 전체 확정하지 않는다.
    """
    from ...contracts import QualificationRequirement
    from ....qualification.rules import judgment as rules

    dates, rows, observations = _validated_context(
        profile, preflight_case_id, reference_date, anchor_dates, record_observations)
    # Snapshot 내용은 결과 지문으로만 남긴다. 사용자 자료를 audit에 복사하지 않는다.
    context_sha = _sha(_json({"profile": profile.model_dump(mode="json"),
        "preflight_case_id": preflight_case_id, "reference_date": reference_date.isoformat(), "anchors": {k: v.isoformat() for k, v in dates.items()},
        "observations": [{"ref": row.record_ref, "basis": row.basis_id, "months": row.operation_months,
                          "meals": row.daily_meals, "tax": row.amount_tax_basis}
                         for row in sorted(rows, key=lambda item: item.record_ref)], "rule_version": rules.RULE_VERSION}))
    base = dict(candidate_id=decision.candidate_id, company_id=profile.company_id, role=decision.role,
                context_sha256=context_sha, rule_version=rules.RULE_VERSION)
    if decision.graph is None or decision.pending_codes:
        return SemanticJudgment(**base, status="UNKNOWN", atoms=(),
            semantic_sha256=semantic_fingerprint(decision.graph) if decision.graph else None,
            pending_codes=decision.pending_codes or ("NO_RESOLVED_CONDITION_GRAPH",))
    graph = decision.graph
    expected_atoms = {atom.atom_id: atom for atom in graph.atoms}
    if len(decision.atoms) != len(expected_atoms) or {atom.atom_id for atom in decision.atoms} != set(expected_atoms):
        raise ValueError("compiled atoms do not match the graph")
    evaluated: list[AtomEvaluation] = []
    for compiled in decision.atoms:
        data = json.loads(compiled.requirement_json)
        rebuilt = AtomicCondition.from_requirement(compiled.atom_id, data, subject=compiled.subject,
                                                   evidence_ids=data["evidence_keys"])
        if rebuilt != expected_atoms[compiled.atom_id]:
            raise ValueError("canonical payload and graph differ")
        metadata = data["scope"].get("review_semantics")
        if not isinstance(metadata, dict) or metadata.get("version") != SEMANTIC_VERSION:
            raise ValueError("missing semantic scope contract")
        allowed_meta = {"version", "value_role", "record_filters", "time_anchor", "tax_basis"}
        if set(metadata) - allowed_meta:
            raise ValueError("unrecognized semantic scope")
        day = reference_date
        if data.get("period_months") is not None:
            day = dates.get(metadata.get("time_anchor"))
            if day is None:
                evaluated.append(AtomEvaluation(compiled.atom_id, "UNKNOWN", "MISSING_REFERENCE_DATE"))
                continue
        clean_scope = {key: value for key, value in data["scope"].items() if key != "review_semantics"}
        # 현재 이 변환기가 구현한 기존 scope만 통과시킨다.
        if set(clean_scope) - {"aggregation", "experience_field", "client_requirement", "issuer", "role"}:
            raise ValueError("unrecognized legacy scope")
        req = QualificationRequirement.model_validate({**data, "scope": clean_scope})
        filters = metadata["record_filters"]
        if filters:
            if req.type != "PERFORMANCE_COUNT" or req.operator not in (">=", ">") or int(req.value) < 1:
                evaluated.append(AtomEvaluation(compiled.atom_id, "UNKNOWN", "RECORD_FILTER_COMBINATION_UNSUPPORTED"))
                continue
            statuses: dict[str, dict[str, str]] = {}
            # 최소 1건 존재라는 내부 질의를 각 실적 하나에만 적용한다. 이 임시 질의를
            # 공고의 원문 조건/판정 결과로 저장하지 않는다.
            one = req.model_copy(update={"operator": ">=", "value": 1})
            for item in profile.performances:
                single = profile.model_copy(update={"performances": [item], "completeness":
                    profile.completeness.model_copy(update={"performances": True})})
                statuses_for_record = [rules.judge_requirement(one, single,
                    preflight_case_id=preflight_case_id, reference_date=day).status]
                fact = observations.get(item.ref)
                for item_filter in filters:
                    if item_filter["role"] == "OPERATION_DURATION":
                        measured = fact.operation_months if fact else None
                    elif item_filter["role"] == "DAILY_VOLUME":
                        measured = fact.daily_meals if fact else None
                    else:
                        raise ValueError("unsupported record filter role")
                    statuses_for_record.append(_compare(measured, item_filter["operator"], item_filter["value"]))
                statuses[item.ref] = {compiled.atom_id: _all(statuses_for_record)}
            per_record = AtomicCondition.from_requirement(compiled.atom_id,
                {**data, "operator": ">=", "value": 1}, subject="PERFORMANCE_RECORD", evidence_ids=data["evidence_keys"])
            count_graph = ConditionGraph("record", (ConditionNode("record", "ATOM", atom_id=compiled.atom_id),), (per_record,))
            counted = count_matching_records(count_graph, statuses,
                minimum=int(req.value) + (1 if req.operator == ">" else 0),
                collection_complete=profile.completeness.performances)
            refs = [{"kind": "performance", "field": "ref", "value": ref}
                    for ref, state in statuses.items() if state[compiled.atom_id] == "SATISFIED"]
            evaluated.append(AtomEvaluation(compiled.atom_id, counted.status, "SAME_RECORD_FILTERS", _json(refs)))
            continue
        tax_basis = metadata.get("tax_basis", "UNSPECIFIED")
        if req.type == "PERFORMANCE_AMOUNT" and tax_basis != "UNSPECIFIED":
            candidates, _ = rules._performance_candidates(profile, req, day)
            if any(observations.get(item.ref) is None or observations[item.ref].amount_tax_basis != tax_basis
                   for item in candidates):
                evaluated.append(AtomEvaluation(compiled.atom_id, "UNKNOWN", "AMOUNT_TAX_BASIS_UNVERIFIED"))
                continue
        answer = rules.judge_requirement(req, profile, preflight_case_id=preflight_case_id, reference_date=day)
        evaluated.append(AtomEvaluation(compiled.atom_id, answer.status, answer.reason_code,
                                        _json(answer.profile_refs)))
    # 동일 의미의 원자가 raw 의존 규칙 때문에 다르게 판정되면 임의의 한 결과를 선택하지 않는다.
    by_semantics: dict[str, list[str]] = defaultdict(list)
    for answer in evaluated:
        by_semantics[expected_atoms[answer.atom_id].semantic_sha256].append(answer.status)
    aliases = {"ATOM-" + key: values[0] if len(set(values)) == 1 else "UNKNOWN"
               for key, values in by_semantics.items()}
    deduped = deduplicate_atoms(graph)
    conflicts = ("DUPLICATE_JUDGMENT_CONFLICT",) if any(len(set(v)) > 1 for v in by_semantics.values()) else ()
    return SemanticJudgment(**base, status=evaluate_condition_graph(deduped, aliases),
        semantic_sha256=semantic_fingerprint(graph), atoms=tuple(evaluated), pending_codes=conflicts)


@dataclass(frozen=True)
class SemanticAnalysis:
    notice_id: str
    notice_version_id: str
    execution: ReviewExecution
    judgments: tuple[SemanticJudgment, ...]

    def audit(self) -> dict[str, Any]:
        return {"strategy": SEMANTIC_VERSION, "notice_id": self.notice_id,
            "notice_version_id": self.notice_version_id, "execution": self.execution.audit(),
            "semantics": [item.audit() for item in self.execution.decisions if isinstance(item, SemanticDecision)],
            "judgments": [{"candidate_id": item.candidate_id, "company_id": item.company_id,
                "status": item.status, "role": item.role, "semantic_sha256": item.semantic_sha256,
                "context_sha256": item.context_sha256, "rule_version": item.rule_version,
                "pending_codes": list(item.pending_codes), "atom_count": len(item.atoms)} for item in self.judgments],
            "notice_overall_status": None,
            "scope_note": "조항별 판정이다. 조항 간 적용 관계/전체 원문 완전성 검증 없이 공고 전체 판정으로 사용하지 않는다."}


def analyze_qualification_semantics(analysis_input: QualificationAnalysisInput, *,
                                    structured_extract: StructuredExtractor,
                                    profile: CompanyProfileSnapshot, preflight_case_id: str,
                                    reference_date: date, anchor_dates: Mapping[str, date] | None = None,
                                    record_observations: Iterable[RecordObservation] = (),
                                    options: ReviewOptions | None = None) -> SemanticAnalysis:
    """명시적 실험 진입점. 기존 analyze_qualification_documents와 HTTP API는 그대로다.

    출력은 legacy RequirementAnalysisResult가 아닌 그래프와 조항별 판정의 별도 내부 계약이다.
    default를 바꾸거나 의미 그래프를 평탄화해 기존 DB에 저장하지 않는다.
    """
    options = options or ReviewOptions()
    dates, observations, _ = _validated_context(
        profile, preflight_case_id, reference_date, anchor_dates, record_observations)
    blocks = [{**block, "document_id": doc.document_id, "source_sha256": doc.file_sha256,
               "extracted_text_sha256": doc.extracted_text_sha256}
              for doc in analysis_input.documents for block in doc.extracted_blocks]
    inventory = build_review_inventory(blocks, notice_version_id=analysis_input.notice_version_id)
    plan = plan_review_requests(inventory, max_body_chars=options.max_body_chars,
        max_targets_per_request=options.max_targets_per_request, neighbor_radius=options.neighbor_radius)
    execution = execute_review_plan(plan, structured_extract=structured_extract, options=options,
                                     response_contract=semantic_response_contract())
    judgments = tuple(judge_semantic_decision(item, profile, preflight_case_id=preflight_case_id,
        reference_date=reference_date, anchor_dates=dates, record_observations=observations)
        for item in execution.decisions if isinstance(item, SemanticDecision) and item.status == "REQUIREMENT")
    return SemanticAnalysis(analysis_input.notice_id, analysis_input.notice_version_id, execution, judgments)
