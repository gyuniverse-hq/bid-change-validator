"""사업계획서 초안 생성 테스트.

이 기능의 핵심 주장은 "확정된 결과를 바꾸지 않는다" 와 "지어내지 않는다" 이므로,
테스트도 그 두 가지가 깨지는 방향을 먼저 본다. 생성 품질은 모델의 몫이라
여기서 재지 않는다 — 대신 **모델에게 무엇을 줬는지**를 고정한다.
"""

from apps.api.app.ai.narration.business_plan import (
    BUSINESS_PLAN_SYSTEM_PROMPT,
    DRAFT_DISCLAIMER,
    BusinessPlanInputs,
    generate_business_plan_draft,
)


BRIEFING_TEXT = """[참가자격 판정] 적격
- 최근 3년 이내 5억원 이상 실적: 충족
  근거: "최근 3년 이내 5억원 이상 실적을 보유한 업체" (p.2)

[계약조항 검토] 확인 필요 없음
"""


def test_the_model_sees_only_the_settled_briefing_and_the_user_inputs() -> None:
    captured = {}

    def narrate(system_prompt: str, body: str) -> str:
        captured["system"] = system_prompt
        captured["body"] = body
        return "# 1. 사업 이해 및 제안 목표\n검토가 필요한 초안"

    result = generate_business_plan_draft(
        BRIEFING_TEXT,
        BusinessPlanInputs(
            company_overview="공공 정보시스템 구축 경험 보유",
            approach="단계별 이관과 검증",
        ),
        notice_id="R26BK01705963",
        judgment_count=1,
        flagged_clause_count=0,
        narrate=narrate,
    )

    assert result.status == "OK"
    assert result.disclaimer == DRAFT_DISCLAIMER
    assert result.notice_id == "R26BK01705963"
    # 어떤 근거 위에서 쓴 초안인지 되짚을 수 있어야 한다.
    assert result.source == {
        "notice_id": "R26BK01705963",
        "judgment_count": 1,
        "flagged_clause_count": 0,
    }

    # 지어내지 말라는 지시가 프롬프트에서 사라지면 이 기능의 전제가 무너진다.
    assert captured["system"] == BUSINESS_PLAN_SYSTEM_PROMPT
    assert "판정을 바꾸거나" in captured["system"]
    assert "[담당자 확인 필요:" in captured["system"]

    # 모델이 본 본문은 확정 텍스트 + 사용자 입력, 그 둘뿐이다.
    assert "[참가자격 판정] 적격" in captured["body"]
    assert "최근 3년 이내 5억원 이상 실적을 보유한 업체" in captured["body"]
    assert "단계별 이관과 검증" in captured["body"]


def test_an_empty_briefing_is_refused_before_the_model_is_called() -> None:
    """근거 없이 쓴 초안이 이 기능에서 가장 나쁜 결과다.

    브리핑 객체 대신 텍스트를 받게 되면서 "내용이 비어 있을 수 없다"는 보장이
    사라졌으므로, 그 자리를 이 검사가 대신한다.
    """
    called = False

    def narrate(_system: str, _body: str) -> str:
        nonlocal called
        called = True
        return "초안"

    result = generate_business_plan_draft(
        "   \n  ",
        BusinessPlanInputs(proposal_goal="안정적 전환"),
        narrate=narrate,
    )

    assert result.status == "MISSING_BRIEFING"
    assert called is False


def test_missing_user_input_and_missing_narrator_are_told_apart() -> None:
    """둘 다 '초안 없음'이지만 담당자가 할 일이 다르다 — 입력을 채우거나, 키를 넣거나."""
    empty = generate_business_plan_draft(
        BRIEFING_TEXT, BusinessPlanInputs(), narrate=lambda _s, _b: "unused"
    )
    unavailable = generate_business_plan_draft(
        BRIEFING_TEXT, BusinessPlanInputs(proposal_goal="안정적 전환"), narrate=None
    )

    assert empty.status == "EMPTY_INPUT"
    assert unavailable.status == "NARRATOR_UNAVAILABLE"
    # 초안이 안 나온 경우에도 면책 문구는 남는다 — 화면이 분기하지 않도록.
    assert empty.disclaimer == DRAFT_DISCLAIMER


def test_generation_failure_is_returned_as_a_result_not_an_exception() -> None:
    """모델 호출 실패로 API 가 500 을 내면 안 된다."""

    def broken(_system: str, _body: str) -> str:
        raise RuntimeError("model unavailable")

    failed = generate_business_plan_draft(
        BRIEFING_TEXT, BusinessPlanInputs(additional_notes="보안 강조"), narrate=broken
    )
    blank = generate_business_plan_draft(
        BRIEFING_TEXT,
        BusinessPlanInputs(additional_notes="보안 강조"),
        narrate=lambda _s, _b: " ",
    )

    assert failed.status == "FAILED"
    assert "오류" in failed.text
    # 빈 문자열도 성공이 아니다. 빈 초안이 화면에 뜨면 사용자는 이유를 알 수 없다.
    assert blank.status == "FAILED"


def test_only_filled_inputs_reach_the_model() -> None:
    """빈 칸을 라벨만 남겨 보내면 모델이 그 자리를 지어내기 쉬워진다."""
    rendered = BusinessPlanInputs(
        company_overview="공공 SI 10년", schedule="  "
    ).render()

    assert "회사 및 보유 역량: 공공 SI 10년" in rendered
    assert "일정" not in rendered
    assert BusinessPlanInputs().render() == "(추가 입력 없음)"
