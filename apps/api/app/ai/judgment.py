"""Deterministic qualification judgment over canonical requirements and company facts.

The LLM is not used in this layer. Requirement extraction produces canonical
operands; this module compares them against a frozen company-profile snapshot.

A missing fact is not automatically a negative fact. Collection-backed profile
areas (staff roles, performances, certifications) carry explicit completeness
flags so an absent item can remain UNKNOWN until the user confirms the profile.
"""

from __future__ import annotations

import calendar
import math
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .contracts import Judgment, QualificationRequirement
from .askability import unsafe_clause_reason


RULE_VERSION = "qualification-rules-v0.2"
OverallQualificationStatus = Literal["eligible", "ineligible", "insufficient_data"]


class ProfileCompleteness(BaseModel):
    region: bool = True
    company_size: bool = True
    industries: bool = True
    staff_total: bool = True
    staff_roles: bool = False
    performances: bool = False
    certifications: bool = False


class ProfileIndustryFact(BaseModel):
    code: str
    name: str
    verified: bool = False


class ProfileStaffRoleFact(BaseModel):
    role_name: str
    headcount: int = Field(ge=0)
    verified: bool = False


class ProfileStaffFact(BaseModel):
    total_count: int = Field(ge=0)
    verified: bool = False
    roles: list[ProfileStaffRoleFact] = Field(default_factory=list)


class ProfilePerformanceFact(BaseModel):
    ref: str
    name: str
    client_name: str | None = None
    client_institution_code: str | None = None
    amount: int = Field(ge=0)
    started_at: date | None = None
    completed_at: date
    fields: list[str] = Field(default_factory=list)
    verified: bool = False


class ProfileCertificationFact(BaseModel):
    ref: str
    name: str
    issuer_name: str | None = None
    issued_at: date | None = None
    expires_at: date | None = None
    verified: bool = False


class CompanyProfileSnapshot(BaseModel):
    company_id: str
    region_code: str | None = None
    region_name: str | None = None
    company_size: str | None = None
    industries: list[ProfileIndustryFact] = Field(default_factory=list)
    staff: ProfileStaffFact | None = None
    performances: list[ProfilePerformanceFact] = Field(default_factory=list)
    certifications: list[ProfileCertificationFact] = Field(default_factory=list)
    completeness: ProfileCompleteness = Field(default_factory=ProfileCompleteness)


class JudgmentEvaluation(BaseModel):
    judgments: list[Judgment]
    overall_status: OverallQualificationStatus


_EVIDENCE_REQUIRED_TYPES = {
    "PERFORMANCE_AMOUNT",
    "PERFORMANCE_COUNT",
    "INDUSTRY",
    "STAFF",
    "REGISTRATION_CERTIFICATION",
    "EXPERIENCE_FIELD",
}

_COMPANY_SIZE_ALIASES: dict[str, set[str]] = {
    "소상공인": {"MICRO"},
    "소기업": {"MICRO", "SMALL"},
    "중소기업": {"MICRO", "SMALL", "MEDIUM"},
    "중견기업": {"MID_SIZED"},
    "대기업": {"LARGE"},
}


def _norm(value: object | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s\-_./(),]+", "", str(value).casefold())


def _profile_ref(kind: str, field: str, value: object) -> dict[str, str]:
    return {"kind": kind, "field": field, "value": str(value)}


def _requires_evidence(requirement: QualificationRequirement) -> bool:
    return requirement.type in _EVIDENCE_REQUIRED_TYPES


def _judgment(
    *,
    requirement: QualificationRequirement,
    preflight_case_id: str,
    status: Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"],
    basis_type: Literal["PROFILE", "USER_ANSWER", "NONE"],
    evidence_held: bool = False,
    reason_code: Literal[
        "RULE_MATCH",
        "RULE_MISMATCH",
        "INSUFFICIENT_DATA",
        "NEEDS_REVIEW",
        "UNSUPPORTED_REQUIREMENT",
    ],
    profile_refs: list[dict[str, str]] | None = None,
    rule_version: str = RULE_VERSION,
) -> Judgment:
    return Judgment(
        judgment_key=f"JUDG:{preflight_case_id}:{requirement.requirement_key}",
        preflight_case_id=preflight_case_id,
        notice_version_id=requirement.notice_version_id,
        requirement_key=requirement.requirement_key,
        status=status,
        basis_type=basis_type,
        evidence_held=evidence_held,
        reason_code=reason_code,
        requires_evidence=_requires_evidence(requirement),
        profile_refs=list(profile_refs or []),
        requirement_evidence_keys=list(requirement.evidence_keys),
        rule_version=rule_version,
    )


def _unknown(
    requirement: QualificationRequirement,
    preflight_case_id: str,
    *,
    unsupported: bool = False,
) -> Judgment:
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNKNOWN",
        basis_type="NONE",
        reason_code="UNSUPPORTED_REQUIREMENT" if unsupported else "INSUFFICIENT_DATA",
    )


def _compare_number(observed: float, operator: str | None, expected: object | None) -> bool | None:
    try:
        target = float(expected)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(target) or not math.isfinite(observed):
        return None
    if operator == ">=":
        return observed >= target
    if operator == ">":
        return observed > target
    if operator == "<=":
        return observed <= target
    if operator == "<":
        return observed < target
    if operator in {"=", "MATCH"}:
        return observed == target
    return None


def _compare_range(observed: float, scope: dict[str, object]) -> bool | None:
    minimum = scope.get("min")
    maximum = scope.get("max")
    min_operator = str(scope.get("min_operator") or ">=")
    max_operator = str(scope.get("max_operator") or "<=")

    if minimum is not None:
        lower = _compare_number(observed, min_operator, minimum)
        if lower is None:
            return None
        if not lower:
            return False
    if maximum is not None:
        upper = _compare_number(observed, max_operator, maximum)
        if upper is None:
            return None
        if not upper:
            return False
    return True if minimum is not None or maximum is not None else None


def _subtract_months(day: date, months: float | int) -> date:
    count = max(0, int(round(float(months))))
    absolute = day.year * 12 + day.month - 1 - count
    year, month0 = divmod(absolute, 12)
    month = month0 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def _string_match(observed: str, expected: object | None) -> bool:
    left = _norm(observed)
    right = _norm(expected)
    if not left or not right:
        return False
    return left == right or right in left or left in right


def _performance_candidates(
    profile: CompanyProfileSnapshot,
    requirement: QualificationRequirement,
    reference_date: date,
) -> list[ProfilePerformanceFact]:
    cutoff = (
        _subtract_months(reference_date, requirement.period_months)
        if requirement.period_months is not None
        else None
    )
    client_requirement = str(requirement.scope.get("client_requirement") or "").strip()

    candidates: list[ProfilePerformanceFact] = []
    for item in profile.performances:
        if item.completed_at > reference_date:
            continue
        if cutoff is not None and item.completed_at < cutoff:
            continue
        field = requirement.scope.get("experience_field")
        if field and not any(_string_match(value, field) for value in [item.name, *item.fields]):
            continue
        if client_requirement:
            client_ok = _string_match(item.client_name or "", client_requirement)
            if not client_ok and _norm(client_requirement) == _norm("공공기관"):
                client_ok = bool(item.client_institution_code) or "공공" in _norm(item.client_name)
            if not client_ok:
                continue
        candidates.append(item)
    return candidates


def _judge_region(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    observed = profile.region_name or profile.region_code
    if not observed:
        return _unknown(requirement, preflight_case_id)
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    matched = _string_match(observed, requirement.value)
    if not matched and not profile.completeness.region:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if matched else "UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MATCH" if matched else "RULE_MISMATCH",
        profile_refs=[_profile_ref("company", "region", observed)],
    )


def _judge_company_size(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    observed = profile.company_size
    if not observed:
        return _unknown(requirement, preflight_case_id)
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)

    expected_text = str(requirement.value).strip()
    allowed = _COMPANY_SIZE_ALIASES.get(expected_text)
    matched = observed in allowed if allowed is not None else _string_match(observed, expected_text)
    if not matched and not profile.completeness.company_size:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if matched else "UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MATCH" if matched else "RULE_MISMATCH",
        profile_refs=[_profile_ref("company", "company_size", observed)],
    )


def _judge_industry(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)

    match = next(
        (
            item
            for item in profile.industries
            if _norm(item.name) == _norm(requirement.value)
            or _norm(item.code) == _norm(requirement.value)
        ),
        None,
    )
    if match is not None:
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED",
            basis_type="PROFILE",
            evidence_held=match.verified,
            reason_code="RULE_MATCH",
            profile_refs=[
                _profile_ref("industry", "code", match.code),
                _profile_ref("industry", "name", match.name),
            ],
        )
    if not profile.completeness.industries:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MISMATCH",
        profile_refs=[],
    )


def _judge_staff(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    staff = profile.staff
    if staff is None:
        return _unknown(requirement, preflight_case_id)

    role = str(requirement.scope.get("role") or "").strip()
    if role:
        matched_role = next(
            (item for item in staff.roles if _string_match(item.role_name, role)),
            None,
        )
        if matched_role is None:
            if not profile.completeness.staff_roles:
                return _unknown(requirement, preflight_case_id)
            return _judgment(
                requirement=requirement,
                preflight_case_id=preflight_case_id,
                status="UNSATISFIED",
                basis_type="PROFILE",
                reason_code="RULE_MISMATCH",
                profile_refs=[],
            )
        if requirement.operator == "MATCH" and requirement.value is not None:
            matched = _string_match(matched_role.role_name, requirement.value)
        else:
            compared = _compare_number(
                matched_role.headcount, requirement.operator, requirement.value
            )
            if compared is None:
                return _unknown(requirement, preflight_case_id, unsupported=True)
            matched = compared
        if not matched and not profile.completeness.staff_roles:
            return _unknown(requirement, preflight_case_id)
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED" if matched else "UNSATISFIED",
            basis_type="PROFILE",
            evidence_held=matched_role.verified,
            reason_code="RULE_MATCH" if matched else "RULE_MISMATCH",
            profile_refs=[
                _profile_ref("staff_role", "role_name", matched_role.role_name),
                _profile_ref("staff_role", "headcount", matched_role.headcount),
            ],
        )

    compared = _compare_number(staff.total_count, requirement.operator, requirement.value)
    if compared is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if not compared and not profile.completeness.staff_total:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if compared else "UNSATISFIED",
        basis_type="PROFILE",
        evidence_held=staff.verified,
        reason_code="RULE_MATCH" if compared else "RULE_MISMATCH",
        profile_refs=[_profile_ref("staff", "total_count", staff.total_count)],
    )


def _judge_performance_amount(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    candidates = _performance_candidates(profile, requirement, reference_date)
    if not candidates:
        if not profile.completeness.performances:
            return _unknown(requirement, preflight_case_id)
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="UNSATISFIED",
            basis_type="PROFILE",
            reason_code="RULE_MISMATCH",
        )

    aggregation = str(requirement.scope.get("aggregation") or "UNSPECIFIED").upper()
    if aggregation == "SUM":
        observed = float(sum(item.amount for item in candidates))
        contributing = candidates
    else:
        best = max(candidates, key=lambda item: item.amount)
        observed = float(best.amount)
        contributing = [best]

    compared = (
        _compare_range(observed, requirement.scope)
        if requirement.operator == "RANGE"
        else _compare_number(observed, requirement.operator, requirement.value)
    )
    if compared is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if aggregation == "UNSPECIFIED" and len(candidates) > 1:
        summed = sum(item.amount for item in candidates)
        sum_compared = _compare_range(summed, requirement.scope) if requirement.operator == "RANGE" else _compare_number(summed, requirement.operator, requirement.value)
        if sum_compared != compared:
            return _unknown(requirement, preflight_case_id, unsupported=True)
    if not compared and not profile.completeness.performances:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if compared else "UNSATISFIED",
        basis_type="PROFILE",
        evidence_held=all(item.verified for item in contributing),
        reason_code="RULE_MATCH" if compared else "RULE_MISMATCH",
        profile_refs=[
            _profile_ref("performance", "ref", item.ref) for item in contributing
        ]
        + [_profile_ref("performance", "observed_amount", int(observed))],
    )


def _judge_performance_count(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    candidates = _performance_candidates(profile, requirement, reference_date)
    observed = len(candidates)
    compared = _compare_number(observed, requirement.operator, requirement.value)
    if compared is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if not compared and not profile.completeness.performances:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if compared else "UNSATISFIED",
        basis_type="PROFILE",
        evidence_held=bool(candidates) and all(item.verified for item in candidates),
        reason_code="RULE_MATCH" if compared else "RULE_MISMATCH",
        profile_refs=[
            _profile_ref("performance", "ref", item.ref) for item in candidates
        ]
        + [_profile_ref("performance", "observed_count", observed)],
    )


def _judge_experience_field(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    candidates = _performance_candidates(profile, requirement, reference_date)
    matched = next(
        (
            item
            for item in candidates
            if any(_string_match(field, requirement.value) for field in item.fields)
            or _string_match(item.name, requirement.value)
        ),
        None,
    )
    if matched is not None:
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED",
            basis_type="PROFILE",
            evidence_held=matched.verified,
            reason_code="RULE_MATCH",
            profile_refs=[_profile_ref("performance", "ref", matched.ref)],
        )
    if not profile.completeness.performances:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MISMATCH",
    )


def _judge_certification(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)

    issuer_requirement = str(requirement.scope.get("issuer") or "").strip()
    name_matches = [
        item
        for item in profile.certifications
        if _string_match(item.name, requirement.value)
    ]
    valid_matches = [
        item
        for item in name_matches
        if (not issuer_requirement or _string_match(item.issuer_name or "", issuer_requirement))
        and (item.expires_at is None or item.expires_at >= reference_date)
        and (item.issued_at is None or item.issued_at <= reference_date)
    ]
    if valid_matches:
        item = valid_matches[0]
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED",
            basis_type="PROFILE",
            evidence_held=item.verified,
            reason_code="RULE_MATCH",
            profile_refs=[
                _profile_ref("certification", "ref", item.ref),
                _profile_ref("certification", "name", item.name),
            ],
        )

    if not profile.completeness.certifications:
        return _unknown(requirement, preflight_case_id)

    refs = [
        _profile_ref("certification", "ref", item.ref)
        for item in name_matches
    ]
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MISMATCH",
        profile_refs=refs,
    )


def judge_requirement(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    *,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    if unsafe_clause_reason(requirement.raw) or requirement.condition_complexity == "composite":
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if requirement.type == "REGION":
        return _judge_region(requirement, profile, preflight_case_id)
    if requirement.type == "COMPANY_SIZE":
        return _judge_company_size(requirement, profile, preflight_case_id)
    if requirement.type == "INDUSTRY":
        return _judge_industry(requirement, profile, preflight_case_id)
    if requirement.type == "STAFF":
        return _judge_staff(requirement, profile, preflight_case_id)
    if requirement.type == "PERFORMANCE_AMOUNT":
        return _judge_performance_amount(
            requirement, profile, preflight_case_id, reference_date
        )
    if requirement.type == "PERFORMANCE_COUNT":
        return _judge_performance_count(
            requirement, profile, preflight_case_id, reference_date
        )
    if requirement.type == "EXPERIENCE_FIELD":
        return _judge_experience_field(
            requirement, profile, preflight_case_id, reference_date
        )
    if requirement.type == "REGISTRATION_CERTIFICATION":
        return _judge_certification(
            requirement, profile, preflight_case_id, reference_date
        )
    return _unknown(requirement, preflight_case_id, unsupported=True)


def derive_overall_status(
    requirements: list[QualificationRequirement],
    judgments: list[Judgment],
    *,
    analysis_status: str = "SUCCEEDED",
) -> OverallQualificationStatus:
    status_by_key = {item.requirement_key: item.status for item in judgments}
    grouped: dict[str, tuple[str, list[str]]] = {}

    for requirement in requirements:
        if requirement.requirement_role != "mandatory":
            continue
        group_key = requirement.requirement_group_key or requirement.requirement_key
        operator = requirement.group_operator or "ALL_OF"
        current_operator, statuses = grouped.setdefault(group_key, (operator, []))
        if current_operator != operator:
            statuses.append("UNKNOWN")
        statuses.append(status_by_key.get(requirement.requirement_key, "UNKNOWN"))

    group_statuses: list[str] = []
    for operator, statuses in grouped.values():
        if operator == "ANY_OF":
            if "SATISFIED" in statuses:
                group_statuses.append("SATISFIED")
            elif "UNKNOWN" in statuses:
                group_statuses.append("UNKNOWN")
            else:
                group_statuses.append("UNSATISFIED")
        else:
            if "UNSATISFIED" in statuses:
                group_statuses.append("UNSATISFIED")
            elif "UNKNOWN" in statuses:
                group_statuses.append("UNKNOWN")
            else:
                group_statuses.append("SATISFIED")

    if "UNSATISFIED" in group_statuses:
        return "ineligible"
    if "UNKNOWN" in group_statuses or not group_statuses or analysis_status != "SUCCEEDED":
        return "insufficient_data"
    return "eligible"


def judge_requirements(
    requirements: list[QualificationRequirement],
    profile: CompanyProfileSnapshot,
    *,
    preflight_case_id: str,
    reference_date: date,
    analysis_status: str = "SUCCEEDED",
) -> JudgmentEvaluation:
    judgments = [
        judge_requirement(
            requirement,
            profile,
            preflight_case_id=preflight_case_id,
            reference_date=reference_date,
        )
        for requirement in requirements
    ]
    return JudgmentEvaluation(
        judgments=judgments,
        overall_status=derive_overall_status(requirements, judgments, analysis_status=analysis_status),
    )
