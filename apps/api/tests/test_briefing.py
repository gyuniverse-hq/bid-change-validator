"""브리핑과 챗봇 — 모델은 확정된 것을 풀어쓰기만 한다.

여기 테스트는 전부 같은 경계를 다른 쪽에서 확인한다: 판정은 코드가 하고,
모델에게 넘어가는 것은 확정된 사실과 원문 인용뿐이다.
"""

from apps.api.app.ai.extraction.analysis_result import AnalysisDiagnostic
from apps.api.app.ai.narration.briefing import (
    CHAT_SYSTEM_PROMPT,
    answer_question,
    build_briefing,
    narrate_briefing,
    render_briefing_text,
)
from apps.api.app.ai.clause_review.contracts import ClauseFinding, StandardReference
from apps.api.app.ai.contracts import (
    Evidence,
    EvidenceLocation,
    Judgment,
    QualificationRequirement,
)


def _requirement(key="REQ-001", raw="최근 3년 이내 실적 5억원 이상") -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key=key,
        notice_version_id="nv-1",
        type="PERFORMANCE_AMOUNT",
        operator=">=",
        value=500_000_000,
        unit="KRW",
        period_months=36,
        raw=raw,
        evidence_keys=[f"{key}-EVD"],
    )


def _evidence(key="REQ-001-EVD", quote="최근 3년 이내 실적 5억원 이상을 보유한 업체") -> Evidence:
    return Evidence(
        evidence_key=key,
        source_type="NOTICE_DOCUMENT",
        document_id="doc-1",
        notice_version_id="nv-1",
        chunk_id="CHUNK-0002",
        location=EvidenceLocation(page=2, display="p.2"),
        quote=quote,
    )


def _judgment(
    key="REQ-001", status="SATISFIED", reason_code="RULE_MATCH", **kwargs
) -> Judgment:
    payload = {
        "judgment_key": f"JDG-{key}",
        "preflight_case_id": "case-1",
        "notice_version_id": "nv-1",
        "requirement_key": key,
        "status": status,
        "basis_type": "PROFILE",
        "reason_code": reason_code,
        "requirement_evidence_keys": [f"{key}-EVD"],
    }
    payload.update(kwargs)
    return Judgment(**payload)


def _briefing(**kwargs):
    defaults = {
        "judgments": [_judgment()],
        "requirements": [_requirement()],
        "evidence": [_evidence()],
        "overall_status": "eligible",
        "title": "통합플랫폼 구축 사업",
        "notice_id": "R26BK01705963",
    }
    defaults.update(kwargs)
    return build_briefing(**defaults)


# ── 조립 ─────────────────────────────────────────────────────────────────
def test_a_judgment_carries_its_requirement_and_the_notice_text_it_rests_on() -> None:
    briefing = _briefing()
    item = briefing.judgments[0]

    assert item.status_label == "충족"
    assert item.requirement_raw == "최근 3년 이내 실적 5억원 이상"
    assert item.evidence[0].quote == "최근 3년 이내 실적 5억원 이상을 보유한 업체"
    assert item.evidence[0].location == "p.2"
    assert briefing.overall_label == "적격"


def test_a_reason_is_written_by_code_not_by_the_model() -> None:
    """Judgment 에 reason 필드가 없어 사유는 코드가 만든다.

    모델에게 사유를 맡기면 판정과 설명이 어긋날 수 있다.
    """
    briefing = _briefing(
        judgments=[_judgment(status="UNKNOWN", reason_code="INSUFFICIENT_DATA")]
    )

    assert briefing.judgments[0].reason == "판정에 필요한 프로필 정보가 없습니다"


def test_a_satisfied_judgment_on_unverified_paperwork_says_so() -> None:
    briefing = _briefing(judgments=[_judgment(requires_evidence=True)])

    assert "증빙 서류 미확인" in briefing.judgments[0].reason


def test_an_answer_based_judgment_is_marked_as_such() -> None:
    briefing = _briefing(judgments=[_judgment(basis_type="USER_ANSWER")])

    assert briefing.judgments[0].basis == "담당자 답변"
    assert "담당자 답변에 근거" in briefing.judgments[0].reason


def test_evidence_is_found_through_the_requirement_when_the_judgment_omits_it() -> None:
    judgment = _judgment()
    judgment = judgment.model_copy(update={"requirement_evidence_keys": []})

    briefing = _briefing(judgments=[judgment])

    assert briefing.judgments[0].evidence[0].evidence_key == "REQ-001-EVD"


def test_notice_facts_are_carried_with_their_evidence() -> None:
    briefing = _briefing(
        diagnostics=[
            AnalysisDiagnostic(
                code="UNMAPPED_REQUIREMENT",
                message="판정 대상이 아닙니다",
                kind="NOTICE_FACT",
                details={"raw": "부정당업체로 지정되지 않은 자"},
                evidence_keys=["FACT-EVD"],
            ),
            AnalysisDiagnostic(code="UNMAPPED_STAFF", message="구조화 실패", kind="PIPELINE"),
        ],
        evidence=[_evidence(), _evidence(key="FACT-EVD", quote="부정당업체로 지정되지 않은 자")],
    )

    # PIPELINE 진단은 담당자에게 보여줄 공고 사실이 아니다.
    assert [fact.code for fact in briefing.notice_facts] == ["UNMAPPED_REQUIREMENT"]
    assert briefing.notice_facts[0].evidence[0].quote == "부정당업체로 지정되지 않은 자"


def test_counts_and_flagged_clauses_are_derived_not_stored() -> None:
    briefing = _briefing(
        judgments=[
            _judgment("REQ-001", "SATISFIED"),
            _judgment("REQ-002", "UNSATISFIED", "RULE_MISMATCH"),
            _judgment("REQ-003", "UNKNOWN", "INSUFFICIENT_DATA"),
        ],
        clause_findings=[
            ClauseFinding(
                rule_id="warranty_period",
                risk_type="WARRANTY_PERIOD",
                label="하자보수 기간 과다",
                detection_method="STANDARD_DIFF",
                verdict="NEEDS_REVIEW",
                reason="공고 값이 표준을 초과",
                clause_label="5.1",
            ),
            ClauseFinding(
                rule_id="penalty_cap",
                risk_type="LATE_PENALTY",
                label="지체상금 상한",
                detection_method="STANDARD_DIFF",
                verdict="COMPLIANT",
                reason="표준 이내",
            ),
        ],
    )

    assert briefing.counts() == {"SATISFIED": 1, "UNSATISFIED": 1, "UNKNOWN": 1}
    assert [item.rule_id for item in briefing.flagged_clauses()] == ["warranty_period"]


# ── 렌더링 ───────────────────────────────────────────────────────────────
def test_the_rendered_text_carries_the_verdict_its_reason_and_the_quote() -> None:
    text = render_briefing_text(_briefing())

    assert "[참가자격 판정] 적격" in text
    assert "[충족]" in text
    assert "사유:" in text
    assert "공고 원문 (p.2): “최근 3년 이내 실적 5억원 이상을 보유한 업체”" in text


def test_a_flagged_clause_is_rendered_with_the_standard_it_was_measured_against() -> None:
    briefing = _briefing(
        clause_findings=[
            ClauseFinding(
                rule_id="warranty_period",
                risk_type="WARRANTY_PERIOD",
                label="하자보수 기간 과다",
                detection_method="STANDARD_DIFF",
                verdict="NEEDS_REVIEW",
                reason="공고 값이 표준(인수 확인 후 1년)을 초과",
                clause_label="5.1",
                matched_text="인수 확인 후 36개월간 하자보수 책임을 진다",
                standard=StandardReference(
                    description="인수 확인 후 1년",
                    clause_ref="용역계약일반조건 제58조제1항",
                ),
            )
        ]
    )
    text = render_briefing_text(briefing)

    assert "[확인 필요 계약조항] 1건" in text
    assert "5.1항 하자보수 기간 과다" in text
    assert "용역계약일반조건 제58조제1항" in text


def test_a_long_quote_is_clipped_so_the_briefing_is_not_a_copy_of_the_notice() -> None:
    briefing = _briefing(evidence=[_evidence(quote="가" * 900)])
    text = render_briefing_text(briefing)

    assert "…" in text
    assert "가" * 900 not in text


# ── 서술 / 챗봇 ──────────────────────────────────────────────────────────
def test_the_narrator_is_told_not_to_change_a_verdict() -> None:
    captured: dict[str, str] = {}

    def narrate(system_prompt: str, body: str) -> str:
        captured["system"] = system_prompt
        captured["body"] = body
        return "이 공고는 적격으로 판정되었습니다."

    told = narrate_briefing(_briefing(), narrate=narrate)

    assert told.available
    assert "판정을 바꾸거나 새 판정을 추가하지 마라" in captured["system"]
    assert "[참가자격 판정] 적격" in captured["body"]


def test_the_chatbot_only_ever_sees_settled_facts_and_quotes() -> None:
    captured: dict[str, str] = {}

    def narrate(system_prompt: str, body: str) -> str:
        captured["system"] = system_prompt
        captured["body"] = body
        return "실적 요건은 충족으로 판정되었습니다."

    answer = answer_question("실적 요건 어떻게 됐어?", _briefing(), narrate=narrate)

    assert answer.status == "OK"
    assert captured["system"] == CHAT_SYSTEM_PROMPT
    assert "절대 새로 내리지 마라" in captured["system"]
    # 모델이 보는 사실은 브리핑 본문뿐이다.
    assert "[현재 상태]" in captured["body"]
    assert "최근 3년 이내 실적 5억원 이상을 보유한 업체" in captured["body"]
    assert "실적 요건 어떻게 됐어?" in captured["body"]


def test_earlier_turns_are_carried_so_follow_up_questions_work() -> None:
    captured: dict[str, str] = {}

    def narrate(system_prompt: str, body: str) -> str:
        captured["body"] = body
        return "네."

    answer_question(
        "그럼 그건 왜 그래?",
        _briefing(),
        narrate=narrate,
        history=[("실적 요건 어떻게 됐어?", "충족입니다.")],
    )

    assert "[이전 질문]" in captured["body"]
    assert "충족입니다." in captured["body"]


def test_the_chatbot_degrades_without_breaking_the_screen() -> None:
    briefing = _briefing()

    assert answer_question("  ", briefing, narrate=lambda s, b: "x").status == "EMPTY_QUESTION"
    assert answer_question("질문", briefing, narrate=None).status == "NARRATOR_UNAVAILABLE"

    def broken(system_prompt: str, body: str) -> str:
        raise RuntimeError("model unavailable")

    failed = answer_question("질문", briefing, narrate=broken)
    assert failed.status == "FAILED"
    assert "오류" in failed.text
