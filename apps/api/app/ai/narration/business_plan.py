"""Grounded business-plan draft generation from a settled notice briefing.

This is intentionally a narration feature. It does not judge eligibility or
invent company facts: the model receives only `render_briefing_text()` plus the
additional facts the user supplied for this draft.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .briefing import NoticeBriefing, render_briefing_text
from .summary import Narrator


DRAFT_DISCLAIMER = "AI가 작성한 사업계획서 초안입니다. 제출 전에 담당자가 사실과 표현을 검토하세요."

BUSINESS_PLAN_SYSTEM_PROMPT = """너는 나라장터 공고에 제출할 사업계획서 초안을 작성하는 실무 보조자다.
아래 [검토 브리핑]은 코드가 확정한 참가자격 판정, 계약조항 검토, 공고 요약과 원문 근거다.
[사용자 입력]은 담당자가 이 초안을 위해 직접 제공한 회사·수행 정보다.

규칙:
1. 브리핑의 판정을 바꾸거나 새로운 적격·부적격 판정을 내리지 마라.
2. 두 입력에 없는 회사 실적, 인력, 인증, 금액, 일정, 기술, 고객명은 지어내지 마라.
3. 정보가 부족한 내용은 사실처럼 채우지 말고 `[담당자 확인 필요: ...]`로 표시하라.
4. 미충족·확인 불가·확인 필요 계약조항을 숨기지 말고 대응 또는 확인 과제로 적어라.
5. 공고 원문의 요구와 사용자 입력을 구분하고, 확정되지 않은 주장을 단정하지 마라.
6. 아래 고정 목차와 순서를 그대로 사용해 한국어 Markdown으로 작성하라.

# 1. 사업 이해 및 제안 목표
# 2. 추진 전략 및 수행 방안
# 3. 조직·인력 및 역할
# 4. 일정 및 산출물 계획
# 5. 품질·위험 및 계약조건 대응
# 6. 자격요건·제출 전 확인사항
"""


class BusinessPlanInputs(BaseModel):
    company_overview: str = ""
    proposal_goal: str = ""
    approach: str = ""
    differentiators: str = ""
    staffing: str = ""
    schedule: str = ""
    additional_notes: str = ""

    def has_content(self) -> bool:
        return any(str(value).strip() for value in self.model_dump().values())

    def render(self) -> str:
        labels = {
            "company_overview": "회사 및 보유 역량",
            "proposal_goal": "제안 목표",
            "approach": "수행 방안",
            "differentiators": "차별점",
            "staffing": "투입 조직·인력",
            "schedule": "일정·산출물 계획",
            "additional_notes": "기타 요청사항",
        }
        lines = []
        for key, value in self.model_dump().items():
            cleaned = str(value).strip()
            if cleaned:
                lines.append(f"- {labels[key]}: {cleaned}")
        return "\n".join(lines) or "(추가 입력 없음)"


class BusinessPlanDraft(BaseModel):
    text: str = ""
    status: str = "OK"  # OK | EMPTY_INPUT | NARRATOR_UNAVAILABLE | FAILED
    disclaimer: str = DRAFT_DISCLAIMER
    notice_id: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


def generate_business_plan_draft(
    briefing: NoticeBriefing,
    inputs: BusinessPlanInputs,
    *,
    narrate: Narrator | None = None,
) -> BusinessPlanDraft:
    """Generate a fixed-template draft without changing any settled result."""
    source = {
        "notice_id": briefing.notice_id,
        "judgment_count": len(briefing.judgments),
        "flagged_clause_count": len(briefing.flagged_clauses()),
    }
    if not inputs.has_content():
        return BusinessPlanDraft(
            text="사업계획서에 반영할 회사 정보나 수행 방안을 한 가지 이상 입력해 주세요.",
            status="EMPTY_INPUT",
            notice_id=briefing.notice_id,
            source=source,
        )
    if narrate is None:
        return BusinessPlanDraft(
            text="OPENAI_API_KEY가 설정되지 않아 사업계획서 초안을 생성할 수 없습니다.",
            status="NARRATOR_UNAVAILABLE",
            notice_id=briefing.notice_id,
            source=source,
        )

    body = (
        f"[검토 브리핑]\n{render_briefing_text(briefing)}\n\n"
        f"[사용자 입력]\n{inputs.render()}"
    )
    try:
        generated = narrate(BUSINESS_PLAN_SYSTEM_PROMPT, body)
    except Exception as error:  # noqa: BLE001 - generation failure is an API result
        return BusinessPlanDraft(
            text=f"초안 생성 중 오류가 발생했습니다: {error}",
            status="FAILED",
            notice_id=briefing.notice_id,
            source=source,
        )

    cleaned = (generated or "").strip()
    if not cleaned:
        return BusinessPlanDraft(
            text="모델이 빈 초안을 반환했습니다. 다시 시도해 주세요.",
            status="FAILED",
            notice_id=briefing.notice_id,
            source=source,
        )
    return BusinessPlanDraft(
        text=cleaned,
        notice_id=briefing.notice_id,
        source=source,
    )
