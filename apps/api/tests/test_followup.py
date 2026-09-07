from datetime import date

from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.ai.followup import (
    ProfileUpdate,
    apply_profile_update,
    parse_date_raw,
    parse_followup_answer,
)
from apps.api.app.ai.judgment import judge_requirement
from apps.api.app.ai.profile import ExtensionValue, as_profile_view


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


def _extractor(payload: dict):
    """A stand-in for the structured extractor, recording what it was asked."""
    calls: list[tuple[str, str, dict]] = []

    def extract(system_prompt: str, user_body: str, schema: dict) -> dict:
        calls.append((system_prompt, user_body, schema))
        return {
            "answer_type": "제공",
            "certifications": [],
            "region_label": None,
            "performances": [],
            "staff": [],
            **payload,
        }

    extract.calls = calls  # type: ignore[attr-defined]
    return extract


def _parse(requirement, answer_text, payload=None, profile=None, **kwargs):
    return parse_followup_answer(
        requirement,
        "질문",
        answer_text,
        profile=profile,
        structured_extract=_extractor(payload) if payload is not None else None,
        today=TODAY,
        **kwargs,
    )


# ── date reading ─────────────────────────────────────────────────────────
def test_dates_are_read_in_code_and_unreadable_ones_stay_none() -> None:
    assert parse_date_raw("2024-08-30") == date(2024, 8, 30)
    assert parse_date_raw("2024년 8월") == date(2024, 8, 28)
    assert parse_date_raw("2024") == date(2024, 12, 28)
    assert parse_date_raw("작년 8월", today=TODAY) == date(2025, 8, 28)
    assert parse_date_raw("재작년", today=TODAY) == date(2024, 12, 28)
    assert parse_date_raw("2024-02-31") is None
    assert parse_date_raw("얼마 전") is None
    assert parse_date_raw(None) is None


# ── extension answers never reach a model ────────────────────────────────
def test_extension_answer_is_read_without_any_extractor() -> None:
    result = _parse(
        _requirement(requirement_key="REQ-0002-STAFF", type="STAFF", raw="특급기술자 2인 이상"),
        "특급 2명, 고급 3명 있습니다",
    )

    assert result.answer_type == "ANSWERED"
    assert result.updates.extensions["sw_engineer_grade"].value == {"특급": 2, "고급": 3}
    assert result.updates.extensions["sw_engineer_grade"].source == "askback"


def test_unreadable_extension_answer_is_not_guessed() -> None:
    result = _parse(
        _requirement(requirement_key="REQ-0002-STAFF", type="STAFF", raw="특급기술자 2인 이상"),
        "확인해보고 알려드리겠습니다",
    )

    assert result.answer_type == "UNKNOWN"
    assert result.updates.is_empty()
    assert "값을 읽지 못했습니다" in result.rejected[0]


# ── extractor availability ───────────────────────────────────────────────
def test_free_prose_without_an_extractor_reports_instead_of_failing() -> None:
    result = _parse(_requirement(), "작년에 6억원 사업 했습니다")

    assert result.answer_type == "PARSER_UNAVAILABLE"
    assert result.updates.is_empty()


def test_extractor_failure_is_reported_as_a_result() -> None:
    def broken(system_prompt, user_body, schema):
        raise RuntimeError("model unavailable")

    result = parse_followup_answer(
        _requirement(), "질문", "답변", structured_extract=broken, today=TODAY
    )

    assert result.answer_type == "FAILED"
    assert "model unavailable" in result.notes


# ── hallucination guards ─────────────────────────────────────────────────
def test_amount_absent_from_the_answer_is_discarded() -> None:
    result = _parse(
        _requirement(),
        "네, 비슷한 사업 해봤습니다",
        {
            "performances": [
                {
                    "title": "정보시스템 구축",
                    "client_type": "public",
                    "amount_raw": "6억원",
                    "done_raw": "2024년 8월",
                }
            ]
        },
    )

    assert result.updates.performances is None
    assert "환각 의심" in result.rejected[0]


def test_completion_date_absent_from_the_answer_drops_the_row() -> None:
    result = _parse(
        _requirement(),
        "6억 1천만원 사업을 했습니다",
        {
            "performances": [
                {
                    "title": "정보시스템 구축",
                    "client_type": "public",
                    "amount_raw": "6억 1천만원",
                    "done_raw": "2024년 8월",
                }
            ]
        },
    )

    assert result.updates.performances is None
    assert any("완료 시점" in item for item in result.rejected)


def test_certification_name_is_matched_loosely_but_still_checked() -> None:
    result = _parse(
        _requirement(type="REGISTRATION_CERTIFICATION", raw="ISO 27001 인증 보유"),
        "ISO 27001 인증 2023년에 취득했습니다",
        {
            "certifications": [
                {"label": "ISO/IEC 27001", "issued_year_raw": "2023년"},
                {"label": "ISO 9001", "issued_year_raw": None},
            ]
        },
    )

    labels = [item.label for item in result.updates.certifications or []]
    assert labels == ["ISO/IEC 27001"]
    assert (result.updates.certifications or [])[0].issued_year == 2023
    assert any("ISO 9001" in item for item in result.rejected)


def test_region_not_present_in_the_answer_is_discarded() -> None:
    accepted = _parse(
        _requirement(type="REGION", raw="서울 소재 업체"),
        "저희는 서울 강남구에 있습니다",
        {"region_label": "서울 강남구"},
    )
    assert accepted.updates.region is not None
    assert accepted.updates.region.label == "서울 강남구"
    # An officer's answer cannot supply the administrative code.
    assert accepted.updates.region.value is None

    invented = _parse(
        _requirement(type="REGION", raw="서울 소재 업체"),
        "확인 후 알려드리겠습니다",
        {"region_label": "부산광역시"},
    )
    assert invented.updates.region is None
    assert "환각 의심" in invented.rejected[0]


# ── staff ────────────────────────────────────────────────────────────────
def test_staff_headcount_expands_into_people_and_continues_id_numbering() -> None:
    result = _parse(
        _requirement(type="STAFF", raw="경력 5년 이상 인력 2인 이상"),
        "PM 7년 경력 2명 있습니다",
        {
            "staff": [
                {
                    "role": "PM",
                    "career_years_raw": "7년",
                    "grade_raw": None,
                    "count_raw": "2명",
                }
            ]
        },
        profile={"staff": [{"id": "st_01", "career_years": 3}]},
    )

    staff = result.updates.staff or []
    assert [item.id for item in staff] == ["st_02", "st_03"]
    assert all(item.career_years == 7.0 for item in staff)
    assert all(item.source == "askback" for item in staff)


def test_grade_only_staff_answer_explains_where_it_belongs() -> None:
    result = _parse(
        _requirement(type="STAFF", raw="기술인력 2인 이상"),
        "특급 2명 있습니다",
        {
            "staff": [
                {
                    "role": None,
                    "career_years_raw": None,
                    "grade_raw": "특급",
                    "count_raw": "2명",
                }
            ]
        },
    )

    assert result.updates.staff is None
    assert "등급별 인원" in result.rejected[0]


# ── stating "we have none" ───────────────────────────────────────────────
def test_stating_none_records_an_explicit_empty_section() -> None:
    result = _parse(
        _requirement(),
        "해당 실적은 없습니다",
        {"answer_type": "해당없음"},
    )

    assert result.answer_type == "NONE_HELD"
    assert result.updates.performances == []


def test_stating_none_does_not_empty_an_unrelated_section() -> None:
    result = _parse(
        _requirement(type="REGION", raw="서울 소재 업체"),
        "없습니다",
        {"answer_type": "해당없음"},
    )

    assert result.updates.performances is None
    assert result.updates.certifications is None
    assert result.updates.staff is None


# ── merging ──────────────────────────────────────────────────────────────
def test_performances_and_staff_accumulate_while_certifications_dedupe() -> None:
    profile = {
        "performances": [{"id": "pf_01", "title": "기존", "amount": 100, "year": 2024}],
        "certifications": [{"label": "ISO27001"}],
    }
    update = ProfileUpdate(
        performances=[{"id": "pf_02", "title": "신규", "amount": 200, "year": 2025}],
        certifications=[{"label": "ISO27001"}, {"label": "GS인증"}],
    )

    merged = apply_profile_update(profile, update)

    assert [item.id for item in merged.performances or []] == ["pf_01", "pf_02"]
    assert [item.label for item in merged.certifications or []] == ["ISO27001", "GS인증"]


def test_an_explicit_empty_section_replaces_rather_than_appends() -> None:
    merged = apply_profile_update(
        {"performances": [{"id": "pf_01", "amount": 100, "year": 2024}]},
        ProfileUpdate(performances=[]),
    )

    assert merged.performances == []


def test_re_answering_an_extension_overwrites_the_previous_answer() -> None:
    profile = {
        "extensions": {
            "sw_engineer_grade": {"value": {"특급": 1}, "source": "askback"},
            "conglomerate_affiliate": {"value": {"is_affiliate": False}},
        }
    }
    update = ProfileUpdate(
        extensions={"sw_engineer_grade": ExtensionValue(value={"특급": 3})}
    )

    merged = apply_profile_update(profile, update)

    assert merged.extensions["sw_engineer_grade"].value == {"특급": 3}
    assert "conglomerate_affiliate" in merged.extensions


def test_applying_an_update_leaves_the_original_profile_untouched() -> None:
    original = as_profile_view({"performances": [{"id": "pf_01", "amount": 100}]})

    apply_profile_update(
        original, ProfileUpdate(performances=[{"id": "pf_02", "amount": 200}])
    )

    assert len(original.performances) == 1


# ── the loop actually closes ─────────────────────────────────────────────
def test_an_unknown_judgment_becomes_satisfied_after_the_officer_answers() -> None:
    requirement = _requirement()
    profile: dict = {"basic": {}}

    before = judge_requirement(
        requirement, profile, preflight_case_id=CASE_ID, today=TODAY
    )
    assert before.status == "UNKNOWN"
    assert before.follow_up_question

    answer = "작년 8월에 6억 1천만원 규모 정보시스템 구축 사업을 완료했습니다."
    parsed = _parse(
        requirement,
        answer,
        {
            "performances": [
                {
                    "title": "정보시스템 구축",
                    "client_type": "public",
                    "amount_raw": "6억 1천만원",
                    "done_raw": "작년 8월",
                }
            ]
        },
        profile=profile,
    )
    assert parsed.answer_type == "ANSWERED"
    assert parsed.rejected == []

    updated = apply_profile_update(profile, parsed.updates)
    after = judge_requirement(
        requirement, updated, preflight_case_id=CASE_ID, today=TODAY
    )

    assert after.status == "SATISFIED"
    # The company stated this itself, so the document still has to be produced.
    assert after.requires_evidence is True
    assert "자기신고" in after.reason


def test_the_extension_loop_closes_too() -> None:
    requirement = _requirement(
        requirement_key="REQ-0002-STAFF", type="STAFF", raw="특급기술자 2인 이상 참여"
    )
    profile: dict = {"staff": []}

    before = judge_requirement(
        requirement, profile, preflight_case_id=CASE_ID, today=TODAY
    )
    assert before.required_extension_key == "sw_engineer_grade"

    parsed = _parse(requirement, "특급 2명, 고급 3명 있습니다", profile=profile)
    after = judge_requirement(
        requirement,
        apply_profile_update(profile, parsed.updates),
        preflight_case_id=CASE_ID,
        today=TODAY,
    )

    assert after.status == "SATISFIED"
    assert after.basis_type == "USER_ANSWER"
