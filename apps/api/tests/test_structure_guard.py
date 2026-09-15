"""가드가 raw 문장이 아니라 추출이 만든 구조에 묻는지.

[2026-09-15] 이번 주 흔들림의 뿌리 하나: 가드가 문장 단위 이분법이었고, 같은 가드를
판정기가 raw 로 **두 번째** 읽었다. 추출이 ANY_OF 로 담아 둔 대안 묶음(J14 1257/6770/6786)의
raw 에는 '또는' 이 있으니 판정기가 "또는이 있네" 하고 다시 막았다 — 1257 보유 회사가 적합이
아니라 확인 필요. 코덱스의 공고→판정 끝까지 실행이 잡았고 제 브랜치에서 재현했다.

원칙: 가드 평가는 추출이 한 번 하고 구조에 새긴다(condition_complexity, scope.guard).
판정기·askability 는 그 표시가 있는 요건의 raw 를 다시 읽지 않는다. 표시가 없는 요건(예전
저장 행, 골든 고정본)은 예전처럼 raw 를 본다 — 골든 회귀는 이 변경으로 움직이지 않는다.
"""

from __future__ import annotations

from datetime import date

from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.ai.qualification.canonical.legacy_slots import adapt_legacy_slot
from apps.api.app.qualification.rules.askability import classify_askability
from apps.api.app.qualification.rules.clause_safety import GUARD_ASSESSED, assess_clause
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot, judge_requirements


J14_ALTERNATION = (
    "1)「폐기물관리법」 제25조에 따른 폐기물중간처분업 (1257) 또는 폐기물중간재활용업 (6770)"
    "또는 폐기물종합재활용업(6786) 등록업체"
)


def _profile_with(*codes: str) -> CompanyProfileSnapshot:
    return CompanyProfileSnapshot.model_validate({
        "company_id": "C-1",
        "industries": [{"code": c, "name": f"업종{c}", "verified": False} for c in codes],
        "certifications": [],
        "completeness": {
            "certifications": True, "company_size": True, "industries": True,
            "performances": True, "region": True, "staff_roles": True, "staff_total": True,
        },
    })


def test_assess_clause_precedence() -> None:
    # 예외 단서가 원문에서 확인된 원자 → 보류(composite)
    a = assess_clause("폐기물수집·운반업(1227) 등록업체", exception_unresolved=True)
    assert (a.verdict, a.complexity) == ("ABSTAIN", "composite")
    # ANY_OF 로 담긴 원자의 '또는' 은 이미 소화된 것 → KEEP
    a = assess_clause(J14_ALTERNATION, group_operator="ANY_OF")
    assert (a.verdict, a.complexity) == ("KEEP", "simple")
    # 같은 raw 라도 구조 없이 오면(ALL_OF) 대안은 보류
    a = assess_clause(J14_ALTERNATION, group_operator="ALL_OF")
    assert (a.verdict, a.reason) == ("ABSTAIN", "ALTERNATIVE_OR_EXCEPTION_RULE")
    # 코드 없는 절차 문구 → PROCEDURAL
    a = assess_clause("나라장터에 입찰참가자격을 등록한 업체")
    assert a.verdict == "PROCEDURAL"
    # 코드가 있으면 절차 문구는 무시 → KEEP
    a = assess_clause("나라장터에 입찰참가자격을 등록하고 업종코드 1468 을 보유한 업체")
    assert a.verdict == "KEEP"


def test_the_mapper_stamps_every_atom_with_its_assessment() -> None:
    requirements, _ = adapt_legacy_slot(
        {"유형": "업종요건", "raw": J14_ALTERNATION, "업종_raw": "폐기물중간처분업"},
        notice_version_id="NV-1", key_prefix="R",
    )
    assert {i.value for i in requirements} == {"1257", "6770", "6786"}
    assert all(i.scope.get("guard") == GUARD_ASSESSED for i in requirements)
    assert all(i.condition_complexity == "simple" for i in requirements)


def test_an_assessed_any_of_group_is_judged_not_reblocked() -> None:
    """J14 그대로 — 전에는 셋 다 UNSUPPORTED_REQUIREMENT 로 보류돼 1257 보유 회사가
    insufficient_data 였다. 이제 구조를 믿고 판정한다."""
    requirements, _ = adapt_legacy_slot(
        {"유형": "업종요건", "raw": J14_ALTERNATION, "업종_raw": "폐기물중간처분업"},
        notice_version_id="NV-1", key_prefix="R",
    )

    result = judge_requirements(
        requirements, _profile_with("1257"), preflight_case_id="X", reference_date=date(2026, 9, 15)
    )

    assert result.overall_status == "eligible"
    value_of = {i.requirement_key: i.value for i in requirements}
    by_value = {value_of[j.requirement_key]: j.status for j in result.judgments}
    assert by_value["1257"] == "SATISFIED"
    # 없는 코드는 미달이지만 ANY_OF 라 전체를 떨어뜨리지 않는다.
    assert {by_value["6770"], by_value["6786"]} == {"UNSATISFIED"}

    # 어느 대안도 없는 회사는 그대로 부적합.
    none = judge_requirements(
        requirements, _profile_with("1450"), preflight_case_id="X", reference_date=date(2026, 9, 15)
    )
    assert none.overall_status == "ineligible"


def test_an_unassessed_requirement_still_gets_the_raw_guard() -> None:
    """골든 고정본과 예전 저장 행은 표시가 없다. 그들은 예전 그대로 raw 를 본다 — 골든 회귀가
    이 변경으로 움직이지 않는 이유."""
    legacy = QualificationRequirement(
        requirement_key="L", notice_version_id="NV-1", type="INDUSTRY", operator="MATCH",
        value="1257", raw=J14_ALTERNATION, requirement_group_key="G", group_operator="ANY_OF",
    )
    result = judge_requirements([legacy], _profile_with("1257"), preflight_case_id="X", reference_date=date(2026, 9, 15))
    assert result.judgments[0].status == "UNKNOWN"


def test_a_composite_exception_row_is_unknown_and_not_askable() -> None:
    row = QualificationRequirement(
        requirement_key="E", notice_version_id="NV-1", type="INDUSTRY", operator="MATCH",
        value="1227", raw="폐기물수집·운반업(1227) 등록업체", requirement_group_key="G",
        group_operator="ALL_OF", condition_complexity="composite",
        scope={"guard": GUARD_ASSESSED, "guard_reason": "EXCEPTION_UNRESOLVED"},
    )
    result = judge_requirements([row], _profile_with("1227"), preflight_case_id="X", reference_date=date(2026, 9, 15))
    assert result.judgments[0].status == "UNKNOWN"

    decision = classify_askability(row)
    assert decision.askable is False
    assert decision.reason_code == "EXCEPTION_UNRESOLVED"
