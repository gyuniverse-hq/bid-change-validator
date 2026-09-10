from apps.api.app.ai.narration.briefing import build_briefing
from apps.api.app.ai.narration.business_plan import (
    BUSINESS_PLAN_SYSTEM_PROMPT,
    DRAFT_DISCLAIMER,
    BusinessPlanInputs,
    generate_business_plan_draft,
)
from apps.api.app.ai.contracts import Evidence, EvidenceLocation, Judgment, QualificationRequirement


def _briefing():
    requirement = QualificationRequirement(
        requirement_key="REQ-1",
        notice_version_id="NV-1",
        type="PERFORMANCE_AMOUNT",
        operator=">=",
        value=500_000_000,
        unit="KRW",
        raw="최근 3년 이내 5억원 이상 실적",
        evidence_keys=["EVD-1"],
    )
    evidence = Evidence(
        evidence_key="EVD-1",
        source_type="NOTICE_DOCUMENT",
        document_id="DOC-1",
        notice_version_id="NV-1",
        chunk_id="CHUNK-1",
        location=EvidenceLocation(page=2, display="p.2"),
        quote="최근 3년 이내 5억원 이상 실적을 보유한 업체",
    )
    judgment = Judgment(
        judgment_key="J-1",
        preflight_case_id="CASE-1",
        notice_version_id="NV-1",
        requirement_key="REQ-1",
        status="SATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MATCH",
        requirement_evidence_keys=["EVD-1"],
    )
    return build_briefing(
        judgments=[judgment],
        requirements=[requirement],
        evidence=[evidence],
        overall_status="eligible",
        notice_id="R26BK01705963",
        title="통합플랫폼 구축 사업",
    )


def test_draft_uses_only_the_settled_briefing_and_user_inputs() -> None:
    captured = {}

    def narrate(system_prompt: str, body: str) -> str:
        captured["system"] = system_prompt
        captured["body"] = body
        return "# 1. 사업 이해 및 제안 목표\n검토가 필요한 초안"

    result = generate_business_plan_draft(
        _briefing(),
        BusinessPlanInputs(
            company_overview="공공 정보시스템 구축 경험 보유",
            approach="단계별 이관과 검증",
        ),
        narrate=narrate,
    )

    assert result.status == "OK"
    assert result.disclaimer == DRAFT_DISCLAIMER
    assert result.notice_id == "R26BK01705963"
    assert result.source == {
        "notice_id": "R26BK01705963",
        "judgment_count": 1,
        "flagged_clause_count": 0,
    }
    assert captured["system"] == BUSINESS_PLAN_SYSTEM_PROMPT
    assert "판정을 바꾸거나" in captured["system"]
    assert "[담당자 확인 필요:" in captured["system"]
    assert "[참가자격 판정] 적격" in captured["body"]
    assert "최근 3년 이내 5억원 이상 실적을 보유한 업체" in captured["body"]
    assert "단계별 이관과 검증" in captured["body"]


def test_draft_requires_user_input_and_a_narrator() -> None:
    empty = generate_business_plan_draft(
        _briefing(), BusinessPlanInputs(), narrate=lambda _s, _b: "unused"
    )
    unavailable = generate_business_plan_draft(
        _briefing(), BusinessPlanInputs(proposal_goal="안정적 전환"), narrate=None
    )

    assert empty.status == "EMPTY_INPUT"
    assert unavailable.status == "NARRATOR_UNAVAILABLE"
    assert empty.disclaimer == DRAFT_DISCLAIMER


def test_draft_generation_failure_is_returned_without_breaking_the_api() -> None:
    def broken(_system: str, _body: str) -> str:
        raise RuntimeError("model unavailable")

    failed = generate_business_plan_draft(
        _briefing(), BusinessPlanInputs(additional_notes="보안 강조"), narrate=broken
    )
    blank = generate_business_plan_draft(
        _briefing(), BusinessPlanInputs(additional_notes="보안 강조"), narrate=lambda _s, _b: " "
    )

    assert failed.status == "FAILED"
    assert "오류" in failed.text
    assert blank.status == "FAILED"


def test_demo_exposes_the_business_plan_draft_endpoint() -> None:
    from apps.api.app.ai.demo.web import app

    assert "/api/business-plan-draft" in {route.path for route in app.routes}


def test_demo_page_connects_business_plan_form_to_endpoint() -> None:
    from apps.api.app.ai.demo.web import PAGE_PATH

    page = PAGE_PATH.read_text(encoding="utf-8")

    assert 'id="businessPlanBtn"' in page
    assert 'id="businessPlanResult" hidden' in page
    assert 'post("/api/business-plan-draft"' in page
    assert "profile:buildProfile()" in page
    for field in (
        "company_overview",
        "proposal_goal",
        "approach",
        "differentiators",
        "staffing",
        "schedule",
        "additional_notes",
    ):
        assert field in page
