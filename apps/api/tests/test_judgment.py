from datetime import date

from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.ai.judgment import judge_requirement, judge_requirements


TODAY = date(2026, 9, 7)
NOTICE_VERSION_ID = "nv-001"
CASE_ID = "case-001"


def _requirement(**overrides) -> QualificationRequirement:
    payload = {
        "requirement_key": "REQ-0001-AMOUNT",
        "notice_version_id": NOTICE_VERSION_ID,
        "type": "PERFORMANCE_AMOUNT",
        "raw": "최근 3년 이내 5억원 이상 실적",
        "operator": ">=",
        "value": 500_000_000,
        "unit": "KRW",
        "period_months": 36,
    }
    payload.update(overrides)
    return QualificationRequirement(**payload)


def _judge(requirement: QualificationRequirement, profile, **kwargs):
    return judge_requirement(
        requirement, profile, preflight_case_id=CASE_ID, today=TODAY, **kwargs
    )


def _performance(**overrides) -> dict:
    payload = {
        "id": "pf_01",
        "title": "정보시스템 구축",
        "amount": 600_000_000,
        "year": 2025,
        "evidence_status": "verified",
    }
    payload.update(overrides)
    return payload


# ── performance amount ───────────────────────────────────────────────────
def test_single_performance_inside_window_satisfies() -> None:
    judgment = _judge(_requirement(), {"performances": [_performance()]})

    assert judgment.status == "SATISFIED"
    assert judgment.reason_code == "RULE_MATCH"
    assert judgment.basis_type == "PROFILE"
    assert judgment.profile_refs == [{"section": "performances", "id": "pf_01"}]
    assert judgment.judgment_key == f"JDG-{CASE_ID}-REQ-0001-AMOUNT"
    assert judgment.notice_version_id == NOTICE_VERSION_ID


def test_boundary_year_performance_goes_to_review_instead_of_being_counted() -> None:
    # 2023 is the boundary year for a 36-month window ending in 2026-09, and the
    # profile has no completion month, so it can be on either side.
    judgment = _judge(_requirement(), {"performances": [_performance(year=2023)]})

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "NEEDS_REVIEW"
    assert "완료 시점" in judgment.reason
    assert judgment.follow_up_question is not None


def test_performance_older_than_the_window_is_dropped_outright() -> None:
    judgment = _judge(_requirement(), {"performances": [_performance(year=2019)]})

    assert judgment.status == "UNSATISFIED"
    assert judgment.reason_code == "RULE_MISMATCH"


def test_sum_reaching_the_threshold_is_reported_not_claimed() -> None:
    judgment = _judge(
        _requirement(),
        {
            "performances": [
                _performance(id="pf_01", amount=300_000_000),
                _performance(id="pf_02", amount=300_000_000),
            ]
        },
    )

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "NEEDS_REVIEW"
    assert "단건/합산" in judgment.reason


def test_explicit_total_aggregation_settles_the_sum_question() -> None:
    judgment = _judge(
        _requirement(scope={"aggregation": "TOTAL"}),
        {
            "performances": [
                _performance(id="pf_01", amount=300_000_000),
                _performance(id="pf_02", amount=300_000_000),
            ]
        },
    )

    assert judgment.status == "SATISFIED"
    assert "합산" in judgment.reason


def test_missing_performance_section_asks_instead_of_failing_the_company() -> None:
    judgment = _judge(_requirement(), {"basic": {}})

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "INSUFFICIENT_DATA"
    assert judgment.basis_type == "NONE"
    assert judgment.follow_up_question


def test_stated_empty_performance_section_settles_as_unsatisfied() -> None:
    judgment = _judge(_requirement(), {"performances": []})

    assert judgment.status == "UNSATISFIED"
    assert judgment.reason_code == "RULE_MISMATCH"


def test_self_declared_evidence_keeps_the_judgment_but_flags_the_paperwork() -> None:
    judgment = _judge(
        _requirement(), {"performances": [_performance(evidence_status="declared")]}
    )

    assert judgment.status == "SATISFIED"
    assert judgment.evidence_held is False
    assert judgment.requires_evidence is True
    assert "자기신고" in judgment.reason


def test_verified_evidence_needs_no_further_paperwork() -> None:
    judgment = _judge(_requirement(), {"performances": [_performance()]})

    assert judgment.evidence_held is True
    assert judgment.requires_evidence is False


def test_stated_period_that_did_not_normalize_is_not_judged_over_all_history() -> None:
    judgment = _judge(
        _requirement(period_months=None, raw="최근 3년간 5억원 이상 실적"),
        {"performances": [_performance(year=2015)]},
    )

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "NEEDS_REVIEW"
    assert "기간" in judgment.reason


def test_requirement_without_any_period_wording_uses_the_whole_history() -> None:
    judgment = _judge(
        _requirement(period_months=None, raw="5억원 이상 실적 보유"),
        {"performances": [_performance(year=2015)]},
    )

    assert judgment.status == "SATISFIED"


# ── performance count ────────────────────────────────────────────────────
def test_performance_count_satisfied_within_window() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0001-COUNT",
            type="PERFORMANCE_COUNT",
            raw="최근 3년 이내 동일 실적 2건 이상",
            value=2,
            unit="COUNT",
        ),
        {
            "performances": [
                _performance(id="pf_01", year=2025),
                _performance(id="pf_02", year=2024),
            ]
        },
    )

    assert judgment.status == "SATISFIED"


def test_performance_count_needing_a_boundary_row_goes_to_review() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0001-COUNT",
            type="PERFORMANCE_COUNT",
            raw="최근 3년 이내 동일 실적 2건 이상",
            value=2,
            unit="COUNT",
        ),
        {
            "performances": [
                _performance(id="pf_01", year=2025),
                _performance(id="pf_02", year=2023),
            ]
        },
    )

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "NEEDS_REVIEW"


# ── certification ────────────────────────────────────────────────────────
def _certification_requirement(**overrides) -> QualificationRequirement:
    payload = {
        "requirement_key": "REQ-0002-CERT",
        "type": "REGISTRATION_CERTIFICATION",
        "raw": "ISO/IEC 27001 인증 보유 업체",
        "operator": "MATCH",
        "value": "ISO/IEC 27001",
        "scope": {"kind": "CERTIFICATION"},
        "period_months": None,
    }
    payload.update(overrides)
    return _requirement(**payload)


def test_certification_matches_across_spacing_differences() -> None:
    judgment = _judge(
        _certification_requirement(),
        {"certifications": [{"label": "ISO27001", "evidence_status": "verified"}]},
    )

    assert judgment.status == "SATISFIED"
    assert "인증" in judgment.reason


def test_certification_held_but_unmatched_asks_rather_than_rejecting() -> None:
    judgment = _judge(
        _certification_requirement(),
        {"certifications": [{"label": "ISO 9001", "evidence_status": "verified"}]},
    )

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "NEEDS_REVIEW"


def test_stated_empty_certification_list_settles_as_unsatisfied() -> None:
    judgment = _judge(_certification_requirement(), {"certifications": []})

    assert judgment.status == "UNSATISFIED"
    assert "빈 목록" in judgment.reason


# ── region ───────────────────────────────────────────────────────────────
def test_region_requirement_matches_on_label_prefix() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0003-REGION",
            type="REGION",
            raw="서울특별시 소재 업체로 참가 제한",
            operator="MATCH",
            value="서울특별시",
            period_months=None,
        ),
        {"basic": {"region": {"value": "11680", "label": "서울특별시 강남구"}}},
    )

    assert judgment.status == "SATISFIED"


def test_nationwide_region_requirement_needs_no_profile_data() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0003-REGION",
            type="REGION",
            raw="참가 지역 제한 없음(전국)",
            operator="MATCH",
            value="전국",
            period_months=None,
        ),
        {"basic": {}},
    )

    assert judgment.status == "SATISFIED"
    assert judgment.reason == "지역 제한 없음"


# ── staff ────────────────────────────────────────────────────────────────
def test_staff_career_requirement_counts_only_people_with_known_career() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0004-STAFF",
            type="STAFF",
            raw="경력 5년 이상 인력 2인 이상 보유",
            operator=">=",
            value=2,
            unit="PERSON",
            period_months=None,
        ),
        {
            "staff": [
                {"id": "st_01", "career_years": 7, "evidence_status": "verified"},
                {"id": "st_02", "career_years": 6, "evidence_status": "verified"},
                {"id": "st_03", "career_years": 2, "evidence_status": "verified"},
            ]
        },
    )

    assert judgment.status == "SATISFIED"


def test_staff_without_career_information_is_not_judged() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0004-STAFF",
            type="STAFF",
            raw="경력 5년 이상 인력 2인 이상 보유",
            operator=">=",
            value=2,
            unit="PERSON",
            period_months=None,
        ),
        {"staff": [{"id": "st_01"}, {"id": "st_02"}]},
    )

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "INSUFFICIENT_DATA"


def test_plain_headcount_requirement_uses_the_canonical_value() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0004-STAFF",
            type="STAFF",
            raw="상시 인력 3인 이상",
            operator=">=",
            value=3,
            unit="PERSON",
            period_months=None,
        ),
        {"staff": [{"id": f"st_{i}"} for i in range(4)]},
    )

    assert judgment.status == "SATISFIED"


# ── company size ─────────────────────────────────────────────────────────
def _size_requirement(**overrides) -> QualificationRequirement:
    payload = {
        "requirement_key": "REQ-0005-SIZE",
        "type": "COMPANY_SIZE",
        "raw": "대기업·중견기업 참여 제한",
        "operator": "MATCH",
        "value": "중소기업",
        "period_months": None,
    }
    payload.update(overrides)
    return _requirement(**payload)


def test_small_company_passes_a_size_restriction() -> None:
    judgment = _judge(_size_requirement(), {"basic": {"company_size": "중소기업"}})

    assert judgment.status == "SATISFIED"


def test_large_company_fails_a_size_restriction() -> None:
    judgment = _judge(_size_requirement(), {"basic": {"company_size": "대기업"}})

    assert judgment.status == "UNSATISFIED"


def test_unknown_company_size_asks_for_the_size() -> None:
    judgment = _judge(_size_requirement(), {"basic": {}})

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "INSUFFICIENT_DATA"
    assert "기업규모" in (judgment.follow_up_question or "")


def test_affiliation_condition_is_not_settled_by_company_size_alone() -> None:
    judgment = _judge(
        _size_requirement(raw="대기업·중견기업 참여 제한, 상호출자제한기업집단 계열회사 참여 불가"),
        {"basic": {"company_size": "중소기업"}},
    )

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "INSUFFICIENT_DATA"
    assert judgment.required_extension_key == "conglomerate_affiliate"


def test_collected_affiliation_answer_completes_the_size_judgment() -> None:
    judgment = _judge(
        _size_requirement(raw="대기업·중견기업 참여 제한, 상호출자제한기업집단 계열회사 참여 불가"),
        {
            "basic": {"company_size": "중소기업"},
            "extensions": {
                "conglomerate_affiliate": {
                    "value": {"is_affiliate": False},
                    "source": "askback",
                    "evidence_status": "declared",
                }
            },
        },
    )

    assert judgment.status == "SATISFIED"
    assert judgment.basis_type == "USER_ANSWER"


def test_large_company_is_rejected_without_asking_about_affiliation() -> None:
    judgment = _judge(
        _size_requirement(raw="대기업·중견기업 참여 제한, 상호출자제한기업집단 계열회사 참여 불가"),
        {"basic": {"company_size": "대기업"}},
    )

    assert judgment.status == "UNSATISFIED"
    assert judgment.follow_up_question is None


# ── industry and experience field ────────────────────────────────────────
def test_industry_code_match() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0006-INDUSTRY",
            type="INDUSTRY",
            raw="업종 7220 등록 업체",
            operator="MATCH",
            value="7220",
            period_months=None,
        ),
        {"basic": {"industry_codes": {"value": ["7220"], "label": ["소프트웨어 개발"]}}},
    )

    assert judgment.status == "SATISFIED"


def test_experience_field_matches_a_performance_field() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0007-EXPERIENCE",
            type="EXPERIENCE_FIELD",
            raw="정보시스템 구축 분야 수행 경험",
            operator="MATCH",
            value="정보시스템 구축",
            period_months=None,
        ),
        {"performances": [_performance(fields=["정보시스템 구축"])]},
    )

    assert judgment.status == "SATISFIED"


def test_experience_field_without_any_field_information_asks() -> None:
    judgment = _judge(
        _requirement(
            requirement_key="REQ-0007-EXPERIENCE",
            type="EXPERIENCE_FIELD",
            raw="정보시스템 구축 분야 수행 경험",
            operator="MATCH",
            value="정보시스템 구축",
            period_months=None,
        ),
        {"basic": {}},
    )

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "INSUFFICIENT_DATA"


# ── cross-cutting behaviour ──────────────────────────────────────────────
def test_absent_profile_never_produces_a_rejection() -> None:
    judgment = _judge(_requirement(), None)

    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "INSUFFICIENT_DATA"
    assert judgment.basis_type == "NONE"
    assert judgment.follow_up_question


def test_requirement_evidence_keys_travel_onto_the_judgment() -> None:
    judgment = _judge(
        _requirement(evidence_keys=["EV-0001"]), {"performances": [_performance()]}
    )

    assert judgment.requirement_evidence_keys == ["EV-0001"]
    assert judgment.rule_version == "judgment.v1"


def test_question_writer_supplies_wording_and_failure_falls_back_to_template() -> None:
    written = _judge(
        _requirement(),
        {"basic": {}},
        question_writer=lambda requirement: "최근 3년 실적을 알려주시겠어요?\n(두 번째 줄은 버려집니다)",
    )
    assert written.follow_up_question == "최근 3년 실적을 알려주시겠어요?"

    def broken(requirement):
        raise RuntimeError("model unavailable")

    fallback = _judge(_requirement(), {"basic": {}}, question_writer=broken)
    assert fallback.follow_up_question
    assert "충족하시나요" in fallback.follow_up_question


def test_judge_requirements_keeps_one_judgment_per_requirement() -> None:
    requirements = [
        _requirement(),
        _certification_requirement(),
        _size_requirement(),
    ]
    judgments = judge_requirements(
        requirements,
        {"performances": [_performance()], "basic": {"company_size": "중소기업"}},
        preflight_case_id=CASE_ID,
        today=TODAY,
    )

    assert [judgment.requirement_key for judgment in judgments] == [
        requirement.requirement_key for requirement in requirements
    ]
    assert len({judgment.judgment_key for judgment in judgments}) == 3
