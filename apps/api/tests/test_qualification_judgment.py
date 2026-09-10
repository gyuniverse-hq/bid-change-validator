from datetime import date

from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.ai.judgment import CompanyProfileSnapshot, ProfileCertificationFact, ProfileCompleteness, ProfilePerformanceFact, ProfileStaffFact, ProfileStaffRoleFact, judge_requirement, judge_requirements

REFERENCE_DATE = date(2026, 9, 7)


def _requirement(key: str, req_type: str, *, operator: str = "MATCH", value=None, scope=None, period_months=None, group_key=None, group_operator="ALL_OF"):
    return QualificationRequirement(requirement_key=key, requirement_group_key=group_key or f"{key}-GROUP", group_operator=group_operator, notice_version_id="version-1", type=req_type, operator=operator, value=value, scope=scope or {}, period_months=period_months, raw=f"raw:{key}")


def _profile(*, completeness: ProfileCompleteness | None = None, certifications=None):
    return CompanyProfileSnapshot(
        company_id="company-1",
        region_code="11",
        region_name="서울특별시",
        company_size="SMALL",
        staff=ProfileStaffFact(total_count=8, verified=True, roles=[ProfileStaffRoleFact(role_name="개발", headcount=5, verified=True)]),
        performances=[ProfilePerformanceFact(ref="performance-1", name="공공기관 정보시스템 구축", client_name="데모 공공기관", amount=500_000_000, completed_at=date(2026, 6, 30), fields=["공공기관 정보시스템 구축"], verified=True)],
        certifications=list(certifications or []),
        completeness=completeness or ProfileCompleteness(),
    )


def test_golden_baseline_keeps_missing_registration_unknown():
    requirements = [
        _requirement("REQ-REGION", "REGION", value="서울특별시"),
        _requirement("REQ-STAFF", "STAFF", operator=">=", value=5, scope={"role": "개발"}),
        _requirement("REQ-PERFORMANCE", "PERFORMANCE_AMOUNT", operator=">=", value=400_000_000, period_months=36, scope={"client_requirement": "공공기관", "aggregation": "UNSPECIFIED"}),
        _requirement("REQ-REGISTRATION", "REGISTRATION_CERTIFICATION", value="정보통신공사업", scope={"kind": "REGISTRATION"}),
    ]
    profile = _profile(completeness=ProfileCompleteness(staff_roles=True, performances=True, certifications=False))
    result = judge_requirements(requirements, profile, preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    by_key = {item.requirement_key: item for item in result.judgments}
    assert by_key["REQ-REGION"].status == "SATISFIED"
    assert by_key["REQ-STAFF"].status == "SATISFIED"
    assert by_key["REQ-PERFORMANCE"].status == "SATISFIED"
    assert by_key["REQ-REGISTRATION"].status == "UNKNOWN"
    assert result.overall_status == "insufficient_data"


def test_changed_performance_threshold_becomes_unsatisfied_when_profile_is_complete():
    requirement = _requirement("REQ-PERFORMANCE", "PERFORMANCE_AMOUNT", operator=">=", value=600_000_000, period_months=36, scope={"client_requirement": "공공기관", "aggregation": "UNSPECIFIED"})
    result = judge_requirements([requirement], _profile(completeness=ProfileCompleteness(staff_roles=True, performances=True)), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNSATISFIED"
    assert result.overall_status == "ineligible"


def test_changed_performance_threshold_stays_unknown_when_profile_is_incomplete():
    requirement = _requirement("REQ-PERFORMANCE", "PERFORMANCE_AMOUNT", operator=">=", value=600_000_000, period_months=36)
    result = judge_requirements([requirement], _profile(completeness=ProfileCompleteness(performances=False)), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNKNOWN"
    assert result.overall_status == "insufficient_data"


def test_complete_missing_certification_is_unsatisfied():
    requirement = _requirement("REQ-CERT", "REGISTRATION_CERTIFICATION", value="정보통신공사업")
    result = judge_requirements([requirement], _profile(completeness=ProfileCompleteness(certifications=True)), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNSATISFIED"
    assert result.overall_status == "ineligible"


def test_present_valid_certification_is_satisfied_even_before_collection_is_complete():
    requirement = _requirement("REQ-CERT", "REGISTRATION_CERTIFICATION", value="정보통신공사업")
    profile = _profile(certifications=[ProfileCertificationFact(ref="cert-1", name="정보통신공사업", expires_at=date(2027, 12, 31), verified=True)], completeness=ProfileCompleteness(certifications=False))
    result = judge_requirements([requirement], profile, preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "SATISFIED"
    assert result.judgments[0].evidence_held is True


def test_any_of_group_does_not_make_one_failed_alternative_ineligible():
    requirements = [
        _requirement("REQ-ALT-SEOUL", "REGION", value="서울특별시", group_key="REQ-ALT", group_operator="ANY_OF"),
        _requirement("REQ-ALT-BUSAN", "REGION", value="부산광역시", group_key="REQ-ALT", group_operator="ANY_OF"),
    ]
    result = judge_requirements(requirements, _profile(), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.overall_status == "eligible"


<<<<<<< Updated upstream
def test_industry_identifiers_require_exact_match():
    from apps.api.app.ai.judgment import ProfileIndustryFact
    profile = _profile().model_copy(update={"industries": [ProfileIndustryFact(code="11426", name="다른 업종")]})
    req = _requirement("industry", "INDUSTRY", value="1426")
    assert judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).overall_status == "ineligible"


def test_composite_clause_abstains_even_with_matching_company_certification():
    req = _requirement("cert", "REGISTRATION_CERTIFICATION", value="정보통신공사업").model_copy(update={"raw": "공동수급체 구성원 모두 정보통신공사업 등록업체이어야 한다."})
    profile = _profile(certifications=[ProfileCertificationFact(ref="c", name="정보통신공사업")])
    assert judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).judgments[0].status == "UNKNOWN"


def test_partial_policy_keeps_any_of_logic_and_never_promotes_to_eligible():
    reqs = [_requirement("a", "REGION", value="서울특별시", group_key="either", group_operator="ANY_OF"), _requirement("b", "REGION", value="부산광역시", group_key="either", group_operator="ANY_OF")]
    assert judge_requirements(reqs, _profile(), preflight_case_id="c", reference_date=REFERENCE_DATE, analysis_status="PARTIAL").overall_status == "insufficient_data"


def test_performance_amount_cannot_use_unrelated_field_or_future_work():
    req = _requirement("amount", "PERFORMANCE_AMOUNT", operator=">=", value=100, scope={"experience_field": "해외진출"})
    profile = _profile(completeness=ProfileCompleteness(performances=True))
    assert judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).overall_status == "ineligible"
    future = profile.performances[0].model_copy(update={"completed_at": date(2027, 1, 1), "fields": ["해외진출"]})
    profile = profile.model_copy(update={"performances": [future]})
    assert judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).overall_status == "ineligible"
=======
def _certification_case(held_name: str, required_name: str):
    requirement = _requirement(
        "REQ-CERT",
        "REGISTRATION_CERTIFICATION",
        value=required_name,
        scope={"kind": "CERTIFICATION"},
    )
    profile = _profile(
        completeness=ProfileCompleteness(certifications=True),
        certifications=[
            ProfileCertificationFact(ref="certification-1", name=held_name, verified=True)
        ],
    )
    evaluation = judge_requirements(
        [requirement], profile, preflight_case_id="case-1", reference_date=REFERENCE_DATE
    )
    return evaluation.judgments[0]


def test_a_certification_written_with_different_punctuation_still_matches():
    # A notice writing "ISO/IEC 27001" must not disqualify a company that recorded
    # the same certificate as "ISO27001".
    assert _certification_case("ISO27001", "ISO/IEC 27001").status == "SATISFIED"
    assert _certification_case("ISO 27001", "ISO/IEC 27001").status == "SATISFIED"


def test_a_different_standard_number_is_still_unsatisfied():
    # The number is the identity: 9001 is a quality standard, 27001 is security.
    assert _certification_case("ISO 9001", "ISO/IEC 27001").status == "UNSATISFIED"


def test_the_same_number_from_a_different_body_is_still_unsatisfied():
    assert _certification_case("KS 27001", "ISO/IEC 27001").status == "UNSATISFIED"


# ── 기업규모: "참여 제한"은 자격이 아니라 배제다 ──────────────────────────
# 공고는 같은 낱말로 정반대를 가리킨다. "중소기업만 참여 가능"은 참여할 수 있는
# 쪽을, "대기업 및 중견기업 참여 제한"은 참여할 수 없는 쪽을 이름한다. 뒤를 앞으로
# 읽으면 그 공고가 우대하려던 중소기업이 부적격으로 나온다.
def test_a_size_restriction_disqualifies_the_named_sizes_not_the_others() -> None:
    requirement = QualificationRequirement(
        requirement_key="REQ-SIZE",
        notice_version_id="nv-1",
        type="COMPANY_SIZE",
        operator="MATCH",
        value="대기업",
        scope={"restriction": "EXCLUDE"},
        raw="「소프트웨어진흥법」제48조에 따라 대기업 및 중견기업 참여 제한",
    )

    smaller = judge_requirement(
        requirement,
        CompanyProfileSnapshot(company_id="C1", company_size="MEDIUM"),
        preflight_case_id="case-1",
        reference_date=date(2026, 9, 9),
    )
    named = judge_requirement(
        requirement,
        CompanyProfileSnapshot(company_id="C2", company_size="LARGE"),
        preflight_case_id="case-1",
        reference_date=date(2026, 9, 9),
    )

    assert smaller.status == "SATISFIED"
    assert named.status == "UNSATISFIED"


def test_a_size_requirement_without_a_restriction_still_reads_as_who_may_bid() -> None:
    requirement = QualificationRequirement(
        requirement_key="REQ-SIZE",
        notice_version_id="nv-1",
        type="COMPANY_SIZE",
        operator="MATCH",
        value="중소기업",
        raw="중소기업만 참여 가능",
    )

    judgment = judge_requirement(
        requirement,
        CompanyProfileSnapshot(company_id="C1", company_size="MEDIUM"),
        preflight_case_id="case-1",
        reference_date=date(2026, 9, 9),
    )

    assert judgment.status == "SATISFIED"
>>>>>>> Stashed changes
