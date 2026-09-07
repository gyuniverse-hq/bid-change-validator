"""The three places a model writes or reads prose, and the limits on each.

Every test here pins the same boundary from a different side: the model may
describe, quote and advise, but it may never decide. Verdicts come from code.
"""

from pathlib import Path

from apps.api.app.ai.assist import (
    ASSIST_SYSTEM,
    answer_question,
    summarize_profile,
    summarize_state,
)
from apps.api.app.ai.clause_review import detect_standard_diff, make_embedding_fallback
from apps.api.app.ai.clause_review.embedding_fallback import quote_is_grounded
from apps.api.app.ai.clause_review.standards import split_clauses
from apps.api.app.ai.contracts import Judgment, QualificationRequirement
from apps.api.app.ai.summary import REPORT_NARRATIVE_SYSTEM, narrate_report
from apps.api.app.demo import FileProfileStore, FixtureNoticeSource, render_report_text
from apps.api.app.demo import review_notice


REPO_ROOT = Path(__file__).resolve().parents[3]
RFP_PATH = REPO_ROOT / "data" / "demo" / "rfp" / "DEMO_공고_스마트도시플랫폼.txt"

STANDARD_TEXT = """제2장 계약의 이행

제58조(하자보수)
①계약상대자는 사업의 종료를 확인한 후 1년간 발생한 하자에 대하여 보수책임이 있다.

제56조(지식재산권의 귀속)
①이 계약에 의하여 작성된 산출물에 대한 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며, 특약이 없으면 지분은 균등한 것으로 한다.
"""


def _clauses() -> list[dict]:
    return split_clauses("용역계약일반조건", STANDARD_TEXT)


# ── tier two: retrieval + a quoted sentence ──────────────────────────────
def test_a_quote_that_is_not_in_the_source_is_discarded() -> None:
    source = "계약상대자는 품질을 보장하며 발생하는 문제를 자비로 해결한다."

    assert quote_is_grounded("계약상대자는 품질을 보장하며", source) is True
    # Whitespace differences are tolerated; invented content is not.
    assert quote_is_grounded("계약상대자는  품질을 보장하며", source) is True
    assert quote_is_grounded("하자보수 기간은 3년으로 한다", source) is False
    assert quote_is_grounded(None, source) is False


def test_wording_the_lexicon_misses_is_found_by_the_second_tier() -> None:
    # No warranty vocabulary at all, so the regex path cannot reach it.
    chunks = [
        {
            "chunk_id": "CHUNK-0001",
            "clause_label": "5.1",
            "text": "5.1 계약상대자는 품질을 보장하며 인수 후 3년간 발생하는 문제를 자비로 해결한다.",
        }
    ]

    def fake_extract(system_prompt: str, user_body: str, schema: dict) -> dict:
        assert schema["name"] == "clause_evidence"
        # The standard clause text is handed over so the topic is unambiguous.
        assert "표준 조항 원문" in user_body
        return {
            "on_topic": True,
            "quote": "인수 후 3년간 발생하는 문제를 자비로 해결한다",
            "value_raw": "3년간",
            "ownership": None,
        }

    findings = detect_standard_diff(
        chunks,
        _clauses(),
        embedding_fallback=make_embedding_fallback(fake_extract),
    )
    warranty = next(item for item in findings if item.rule_id == "warranty_period")

    assert warranty.verdict == "NEEDS_REVIEW"
    assert warranty.matched_via == "EMBEDDING_LLM"
    # The threshold still came from the published rules, and the comparison
    # still happened in code.
    assert warranty.standard is not None and warranty.standard.value == 12
    assert warranty.notice_value == 36


def test_a_fabricated_quote_stops_the_second_tier_from_reporting() -> None:
    chunks = [
        {
            "chunk_id": "CHUNK-0001",
            "clause_label": "5.1",
            "text": "5.1 계약상대자는 품질을 보장하며 인수 후 3년간 발생하는 문제를 자비로 해결한다.",
        }
    ]

    def hallucinating(system_prompt: str, user_body: str, schema: dict) -> dict:
        return {
            "on_topic": True,
            "quote": "하자보수 기간은 5년으로 한다",  # not in the document
            "value_raw": "5년",
            "ownership": None,
        }

    findings = detect_standard_diff(
        chunks, _clauses(), embedding_fallback=make_embedding_fallback(hallucinating)
    )

    assert all(item.rule_id != "warranty_period" for item in findings)


def test_an_off_topic_answer_reports_nothing() -> None:
    chunks = [{"chunk_id": "CHUNK-0001", "clause_label": "1.1", "text": "1.1 사업명: 테스트"}]

    def off_topic(system_prompt: str, user_body: str, schema: dict) -> dict:
        return {"on_topic": False, "quote": None, "value_raw": None, "ownership": None}

    findings = detect_standard_diff(
        chunks, _clauses(), embedding_fallback=make_embedding_fallback(off_topic)
    )
    assert all(item.matched_via != "EMBEDDING_LLM" for item in findings)


def test_a_failing_extractor_leaves_the_first_tier_result_alone() -> None:
    chunks = [
        {
            "chunk_id": "CHUNK-0001",
            "clause_label": "5.1",
            "text": "5.1 인수 확인 후 36개월간 하자보수 책임을 진다.",
        }
    ]

    def broken(system_prompt: str, user_body: str, schema: dict) -> dict:
        raise RuntimeError("model unavailable")

    findings = detect_standard_diff(
        chunks, _clauses(), embedding_fallback=make_embedding_fallback(broken)
    )
    warranty = next(item for item in findings if item.rule_id == "warranty_period")

    assert warranty.verdict == "NEEDS_REVIEW"
    assert warranty.matched_via == "REGEX"


# ── narrating a finished report ──────────────────────────────────────────
STANDARD_INDEX = REPO_ROOT / "data" / "standards" / "clauses.json"


def _corpus():
    if not STANDARD_INDEX.exists():
        return _clauses()  # trimmed stand-in, enough for the warranty rule
    from apps.api.app.ai.clause_review.standards import load_clauses

    return load_clauses(STANDARD_INDEX)


def _report():
    return review_notice(
        "R26BK01705963",
        notice_source=FixtureNoticeSource(),
        profile_id="DEMO_적격업체",
        profile_store=FileProfileStore(),
        rfp_text=RFP_PATH.read_text(encoding="utf-8"),
        standard_clauses=_corpus(),
    )


def test_a_rendered_report_carries_the_verdict_and_its_grounds() -> None:
    text = render_report_text(_report())

    assert "[참가자격 판정]" in text
    assert "[확인 필요 계약조항]" in text
    assert "하자보수" in text


def test_the_narrator_is_told_not_to_change_a_verdict() -> None:
    captured: dict[str, str] = {}

    def narrate(system_prompt: str, body: str) -> str:
        captured["system"] = system_prompt
        captured["body"] = body
        return "이 공고의 참가자격은 확인이 더 필요합니다."

    told = narrate_report(render_report_text(_report()), narrate=narrate)

    assert told.available
    assert "판정을 바꾸거나 새 판정을 추가하지 마라" in captured["system"]
    assert captured["system"] == REPORT_NARRATIVE_SYSTEM
    assert "[참가자격 판정]" in captured["body"]


def test_narration_failures_are_reported_not_raised() -> None:
    assert narrate_report("리포트", narrate=None).status == "NARRATOR_UNAVAILABLE"
    assert narrate_report("", narrate=lambda s, b: "x").status == "NO_SOURCE"

    def broken(system_prompt: str, body: str) -> str:
        raise RuntimeError("down")

    assert narrate_report("리포트", narrate=broken).status == "FAILED"


# ── the assistant ────────────────────────────────────────────────────────
def _judgment(status: str, reason: str, question: str | None = None) -> Judgment:
    return Judgment(
        judgment_key="JDG-1",
        preflight_case_id="case-1",
        notice_version_id="nv-1",
        requirement_key="REQ-1",
        status=status,  # type: ignore[arg-type]
        basis_type="PROFILE",
        reason_code="RULE_MATCH" if status == "SATISFIED" else "INSUFFICIENT_DATA",
        reason=reason,
        follow_up_question=question,
    )


def _requirement() -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key="REQ-1",
        notice_version_id="nv-1",
        type="PERFORMANCE_AMOUNT",
        raw="최근 3년 이내 실적 5억원 이상",
    )


def test_the_profile_summary_shows_what_was_entered_not_what_was_decided() -> None:
    summary = summarize_profile(FileProfileStore().get("DEMO_적격업체"))

    assert "회사명:" in summary
    assert "보유 인증·면허:" in summary
    assert "사업실적:" in summary
    # No verdict language: this half is the officer's input, nothing else.
    assert "충족" not in summary


def test_an_empty_profile_says_so_rather_than_guessing() -> None:
    assert summarize_profile(None) == "(아직 입력된 항목 없음)"
    assert summarize_profile({}) == "(아직 입력된 항목 없음)"


def test_the_state_given_to_the_assistant_is_only_settled_results() -> None:
    state = summarize_state(
        profile=FileProfileStore().get("DEMO_적격업체"),
        judgments=[_judgment("UNKNOWN", "프로필에 실적 정보 없음", "실적을 알려주시겠어요?")],
        requirements=[_requirement()],
        notice_title="테스트 공고",
        diagnostics=[{"message": "업종제한이 있습니다"}],
    )

    assert "[담당자가 입력한 프로필]" in state
    assert "코드가 확정함" in state
    assert "[확인 불가]" in state
    assert "되묻기 대기 중" in state
    assert "업종제한이 있습니다" in state


def test_the_assistant_is_told_never_to_judge() -> None:
    captured: dict[str, str] = {}

    def narrate(system_prompt: str, body: str) -> str:
        captured["system"] = system_prompt
        captured["body"] = body
        return "실적 정보를 프로필에 입력하시면 판정을 마칠 수 있습니다."

    answer = answer_question(
        "그래서 어떻게 해야 해?", state_summary="[현재 상태] ...", narrate=narrate
    )

    assert answer.status == "OK"
    assert answer.text.startswith("실적 정보를")
    assert "절대 새로 내리지 마라" in captured["system"]
    assert captured["system"] == ASSIST_SYSTEM
    assert "그래서 어떻게 해야 해?" in captured["body"]


def test_an_empty_or_unanswerable_question_degrades_gracefully() -> None:
    assert answer_question("   ", state_summary="x", narrate=lambda s, b: "y").status == (
        "EMPTY_QUESTION"
    )
    assert answer_question("질문", state_summary="x", narrate=None).status == (
        "NARRATOR_UNAVAILABLE"
    )

    def broken(system_prompt: str, body: str) -> str:
        raise RuntimeError("down")

    failed = answer_question("질문", state_summary="x", narrate=broken)
    assert failed.status == "FAILED"
    assert "오류" in failed.text
