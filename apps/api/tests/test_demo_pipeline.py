from pathlib import Path

import pytest

from apps.api.app.ai.notice_requirements import (
    build_notice_requirements,
    extract_notice_facts,
)
from apps.api.app.ai.summary import summarize_notice
from apps.api.app.demo import (
    CsvIndustryCatalog,
    FileProfileStore,
    FixtureNoticeSource,
    NoticePriceBoard,
    decide_overall,
    review_notice,
)
from apps.api.app.demo.pipeline import chunks_from_text


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_NOTICE = "R26BK01705963"
RFP_PATH = REPO_ROOT / "data" / "demo" / "rfp" / "DEMO_공고_스마트도시플랫폼.txt"
STANDARD_INDEX = REPO_ROOT / "data" / "standards" / "clauses.json"

NOTICE_VERSION_ID = "nv-demo"


# ── notice API fields ────────────────────────────────────────────────────
def test_a_service_notice_yields_price_and_facts() -> None:
    item = FixtureNoticeSource().fetch(FIXTURE_NOTICE)
    assert item is not None

    facts = extract_notice_facts(item)
    assert facts.notice_no == FIXTURE_NOTICE
    assert facts.title
    assert facts.institution
    assert facts.price.estimated_price == 320_950_909
    assert facts.price.assigned_budget == 353_046_000
    assert "추정가격 320,950,909원" in facts.price.as_display_lines()


def test_a_restriction_flag_without_its_value_becomes_a_diagnostic() -> None:
    # The 용역 endpoint says indstrytyLmtYn=Y but never lists the permitted
    # industries. Turning that into a requirement would mean judging a company
    # against a criterion nobody has.
    item = FixtureNoticeSource().fetch(FIXTURE_NOTICE)

    requirements, diagnostics = build_notice_requirements(
        item, notice_version_id=NOTICE_VERSION_ID
    )

    codes = {entry["code"] for entry in diagnostics}
    assert "INDUSTRY_LIMIT_WITHOUT_DETAIL" in codes
    assert all(requirement.type != "INDUSTRY" for requirement in requirements)


def test_concrete_restrictions_become_requirements() -> None:
    # 공사/물품 endpoints carry the actual values, and those are judgeable.
    item = {
        "bidNtceNo": "TEST-001",
        "prtcptPsblRgnNm": "서울특별시",
        "lcnsLmtNm": "정보통신공사업/0036",
        "permsnIndstrytyList": "[소프트웨어사업자(컴퓨터관련서비스사업)/1468]",
    }

    requirements, _ = build_notice_requirements(item, notice_version_id=NOTICE_VERSION_ID)
    by_type = {requirement.type: requirement for requirement in requirements}

    assert by_type["REGION"].value == "서울특별시"
    assert by_type["REGISTRATION_CERTIFICATION"].value == "정보통신공사업"
    assert by_type["REGISTRATION_CERTIFICATION"].scope["kind"] == "LICENSE"
    assert by_type["INDUSTRY"].value == "1468"
    assert all(
        requirement.scope["origin"] == "NOTICE_API_FIELD" for requirement in requirements
    )


def test_a_nationwide_notice_produces_no_region_requirement() -> None:
    requirements, diagnostics = build_notice_requirements(
        {"bidNtceNo": "TEST-002", "prtcptPsblRgnNm": "전국"},
        notice_version_id=NOTICE_VERSION_ID,
    )

    assert requirements == []
    assert {entry["code"] for entry in diagnostics} == {"NO_REGION_LIMIT"}


def test_price_never_becomes_a_requirement() -> None:
    requirements, _ = build_notice_requirements(
        {"bidNtceNo": "TEST-003", "presmptPrce": "320950909", "asignBdgtAmt": "353046000"},
        notice_version_id=NOTICE_VERSION_ID,
    )

    # Price is context for a person, not a criterion for a verdict.
    assert requirements == []


# ── the overall verdict is three-valued ──────────────────────────────────
class _Judgment:
    def __init__(self, status: str) -> None:
        self.status = status


def test_one_failed_requirement_disqualifies() -> None:
    assert decide_overall([_Judgment("SATISFIED"), _Judgment("UNSATISFIED")]) == "INELIGIBLE"


def test_an_unanswered_requirement_holds_the_verdict_open() -> None:
    assert decide_overall([_Judgment("SATISFIED"), _Judgment("UNKNOWN")]) == "NEEDS_INFO"


def test_all_satisfied_is_eligible_and_nothing_checked_is_not() -> None:
    assert decide_overall([_Judgment("SATISFIED")]) == "ELIGIBLE"
    assert decide_overall([]) == "NEEDS_INFO"


# ── summary ──────────────────────────────────────────────────────────────
def test_a_summary_is_produced_from_injected_prose() -> None:
    captured: dict[str, str] = {}

    def narrate(system_prompt: str, user_body: str) -> str:
        captured["system"] = system_prompt
        captured["user"] = user_body
        return "  이 사업은 스마트도시 통합플랫폼을 구축하는 용역입니다.  "

    summary = summarize_notice("1. 사업 개요\n1.1 사업명: 테스트", title="테스트 공고", narrate=narrate)

    assert summary.status == "OK"
    assert summary.text == "이 사업은 스마트도시 통합플랫폼을 구축하는 용역입니다."
    assert "판정이 아니라 내용 설명이다" in captured["system"]
    assert "테스트 공고" in captured["user"]


def test_a_missing_narrator_or_source_is_stated_not_invented() -> None:
    assert summarize_notice("본문", narrate=None).status == "NARRATOR_UNAVAILABLE"
    assert summarize_notice("   ", narrate=lambda s, u: "x").status == "NO_SOURCE"


def test_a_failing_narrator_never_breaks_the_review() -> None:
    def broken(system_prompt: str, user_body: str) -> str:
        raise RuntimeError("model unavailable")

    summary = summarize_notice("본문", narrate=broken)
    assert summary.status == "FAILED"
    assert "model unavailable" in summary.notes


# ── connectors ───────────────────────────────────────────────────────────
def test_the_industry_catalog_carries_the_statute_behind_a_code() -> None:
    catalog = CsvIndustryCatalog()
    entry = catalog.by_code("0036")

    assert entry is not None
    assert entry.name == "정보통신공사업"
    assert entry.legal_basis  # 근거법규가 코드에 딸려 온다


def test_demo_profiles_are_all_marked_as_fictional() -> None:
    store = FileProfileStore()
    assert store.list_ids()

    for profile_id in store.list_ids():
        raw = store.raw(profile_id) or {}
        assert raw.get("_demo") is True, f"{profile_id} is not marked as a demo profile"
        assert store.get(profile_id) is not None


def test_an_unknown_notice_returns_none_rather_than_an_empty_report() -> None:
    report = review_notice(
        "NO-SUCH-NOTICE",
        notice_source=FixtureNoticeSource(),
        profile_store=FileProfileStore(),
    )
    assert report is None


# ── end to end ───────────────────────────────────────────────────────────
def _stub_extractor(requirements: list[dict]):
    """Stand in for the LLM extractor.

    The values are the same shape the real extractor emits, and they still pass
    the source-grounding guardrail: `raw` really appears in the demo notice and
    `근거조항` really is one of its clause labels.
    """

    def extract(system_prompt: str, user_body: str, schema: dict) -> dict:
        return {"requirements": requirements}

    return extract


@pytest.mark.skipif(not RFP_PATH.exists(), reason="데모 공고문 픽스처 없음")
def test_a_notice_document_is_reviewed_against_the_standard_without_any_model() -> None:
    report = review_notice(
        FIXTURE_NOTICE,
        notice_source=FixtureNoticeSource(),
        profile_id="DEMO_적격업체",
        profile_store=FileProfileStore(),
        industry_catalog=CsvIndustryCatalog(),
        price_board=NoticePriceBoard(),
        rfp_text=RFP_PATH.read_text(encoding="utf-8"),
        standard_clauses=_load_standard_clauses(),
    )

    assert report is not None
    assert report.is_demo_profile is True
    flagged = {finding.rule_id for finding in report.flagged_clauses()}
    # The demo notice deliberately breaches these; none of it needs a model.
    assert {"warranty_period", "inspection_period", "ip_ownership", "open_ended_scope"} <= flagged


def _load_standard_clauses():
    if not STANDARD_INDEX.exists():
        return None
    from apps.api.app.ai.clause_review.standards import load_clauses

    return load_clauses(STANDARD_INDEX)


def test_extracted_requirements_are_judged_into_a_verdict() -> None:
    # The extractor is stubbed so the judging path is exercised without a network
    # call; the slots are the shape the real extractor emits.
    extracted = [
        {
            "유형": "실적요건",
            "raw": "최근 3년 이내 공공기관 정보시스템 구축 용역 실적 5억원 이상을 보유한 업체",
            "금액_raw": "5억원 이상",
            "기간_raw": "최근 3년",
            "근거조항": "2.2",
        },
        {
            "유형": "인증요건",
            "raw": "ISO/IEC 27001 정보보호 관리체계 인증을 보유한 업체",
            "등록인증_raw": "ISO/IEC 27001",
            "근거조항": "2.3",
        },
    ]

    report = review_notice(
        FIXTURE_NOTICE,
        notice_source=FixtureNoticeSource(),
        profile_id="DEMO_적격업체",
        profile_store=FileProfileStore(),
        rfp_text=RFP_PATH.read_text(encoding="utf-8"),
        structured_extract=_stub_extractor(extracted),
    )

    assert report is not None
    assert report.judgments, "추출된 요건이 판정으로 이어지지 않았습니다"
    assert report.verdict in {"ELIGIBLE", "INELIGIBLE", "NEEDS_INFO"}
    # Every judgment states its grounds; that is the point of the whole pipeline.
    assert all(judgment.reason for judgment in report.judgments)


def test_a_sparse_profile_produces_questions_rather_than_a_rejection() -> None:
    extracted = [
        {
            "유형": "실적요건",
            "raw": "최근 3년 이내 공공기관 정보시스템 구축 용역 실적 5억원 이상을 보유한 업체",
            "금액_raw": "5억원 이상",
            "기간_raw": "최근 3년",
            "근거조항": "2.2",
        }
    ]

    report = review_notice(
        FIXTURE_NOTICE,
        notice_source=FixtureNoticeSource(),
        profile_id="DEMO_정보부족업체",
        profile_store=FileProfileStore(),
        rfp_text=RFP_PATH.read_text(encoding="utf-8"),
        structured_extract=_stub_extractor(extracted),
    )

    assert report is not None
    assert report.verdict == "NEEDS_INFO"
    assert report.open_questions


def test_text_chunking_keeps_clause_labels() -> None:
    chunks = chunks_from_text(RFP_PATH.read_text(encoding="utf-8"))

    assert chunks
    labels = {chunk.get("clause_label") for chunk in chunks}
    assert "3.5" in labels or "2.2" in labels
    assert all(chunk["chunk_id"].startswith("CHUNK-") for chunk in chunks)
