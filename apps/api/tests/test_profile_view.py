from apps.api.app.ai.profile import (
    EVIDENCE_DECLARED,
    CompanyProfileSnapshot,
    ProfileView,
    as_profile_view,
    normalize_company_size,
)


def test_unknown_section_and_empty_section_are_different_answers() -> None:
    unknown = as_profile_view({"basic": {}})
    stated_none = as_profile_view({"basic": {}, "performances": []})

    assert unknown.has("performances") is False
    assert stated_none.has("performances") is True
    assert unknown.performances == stated_none.performances == []


def test_basic_fields_accept_both_wrapped_and_bare_values() -> None:
    view = as_profile_view(
        {
            "basic": {
                "company_name": "가온소프트",
                "region": {"value": "11680", "label": "서울특별시 강남구"},
            }
        }
    )

    assert view.company_name == "가온소프트"
    assert view.region_code == "11680"
    assert view.region_label == "서울특별시 강남구"


def test_region_label_falls_back_to_value_when_no_label_given() -> None:
    view = as_profile_view({"basic": {"region": {"value": "서울"}}})

    assert view.region_label == "서울"


def test_company_size_accepts_korean_labels_and_refuses_to_guess() -> None:
    assert normalize_company_size("중견기업") == "medium"
    assert normalize_company_size("LARGE") == "large"
    assert normalize_company_size("사회적기업") is None
    assert normalize_company_size(None) is None

    view = as_profile_view({"basic": {"company_size": {"value": "중소"}}})
    assert view.company_size == "small"
    assert view.company_size_label == "중소기업"


def test_unrecognized_company_size_keeps_the_wording_but_stays_unjudgeable() -> None:
    view = as_profile_view({"basic": {"company_size": {"value": "사회적기업"}}})

    assert view.company_size == ""
    assert view.company_size_label == "사회적기업"
    assert view.has("company_size") is True


def test_certification_labels_fall_back_to_code() -> None:
    view = as_profile_view(
        {
            "certifications": [
                {"label": "ISO27001", "evidence_status": EVIDENCE_DECLARED},
                {"code": "GS-1", "label": None},
                {"code": None, "label": "  "},
            ]
        }
    )

    assert view.certification_labels() == ["ISO27001", "GS-1"]


def test_industry_codes_normalize_to_a_list() -> None:
    single = as_profile_view({"basic": {"industry_codes": {"value": "7220"}}})
    many = as_profile_view(
        {"basic": {"industry_codes": {"value": ["7220", "6201"], "label": ["소프트웨어"]}}}
    )

    assert single.industry_codes == ["7220"]
    assert many.industry_codes == ["7220", "6201"]
    assert many.industry_labels == ["소프트웨어"]


def test_extension_accessors_never_invent_a_missing_answer() -> None:
    view = as_profile_view(
        {
            "extensions": {
                "sw_engineer_grade": {
                    "value": {"특급": 2},
                    "source": "askback",
                    "evidence_status": EVIDENCE_DECLARED,
                }
            }
        }
    )

    assert view.has_extension("sw_engineer_grade") is True
    assert view.extension_value("sw_engineer_grade") == {"특급": 2}
    assert view.has_extension("conglomerate_affiliate") is False
    assert view.extension_value("conglomerate_affiliate") is None
    assert view.extension_entry("conglomerate_affiliate") is None


def test_empty_profile_is_falsy_and_any_stated_section_makes_it_truthy() -> None:
    assert not ProfileView(None)
    assert not as_profile_view({})
    assert as_profile_view({"performances": []})
    assert as_profile_view({"basic": {"company_name": "가온소프트"}})


def test_as_profile_view_passes_through_view_and_snapshot() -> None:
    snapshot = CompanyProfileSnapshot(profile_id="cmp_01")
    view = ProfileView(snapshot)

    assert as_profile_view(view) is view
    assert as_profile_view(snapshot).profile_id == "cmp_01"
