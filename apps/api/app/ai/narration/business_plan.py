"""확정된 검토 결과를 바탕으로 사업계획서 초안을 만든다.

이것은 판정 기능이 아니라 서술 기능이다. 참가자격을 새로 판단하지 않고 회사
사실을 지어내지도 않는다. 모델이 받는 것은 두 가지뿐이다 — 코드가 확정해서
넘겨준 검토 텍스트, 그리고 담당자가 이 초안을 위해 직접 입력한 내용.

왜 브리핑 객체가 아니라 텍스트를 받는가
---------------------------------------
이 모듈은 원래 `NoticeBriefing` 객체를 받았지만, 실제로 쓰는 것은 네 가지뿐이었다
— 공고 ID, 브리핑을 렌더링한 텍스트, 판정 건수, 확인 필요 조항 수. 객체를 통째로
요구하면 브리핑을 만드는 모듈 전체가 이 기능의 의존성이 된다. 브리핑 생성은
Copilot 쪽에서 담당하므로, 그 경계를 넘지 않도록 결과 텍스트만 받는다.

대신 잃는 보장이 하나 있다. 객체를 받을 때는 내용이 비어 있을 수 없었지만
문자열은 비어 있을 수 있다. 근거 없이 초안을 쓰는 것이 이 기능에서 가장 나쁜
실패라, 빈 텍스트는 생성하지 않고 `MISSING_BRIEFING` 으로 돌려보낸다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from . import Narrator


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
    # OK | MISSING_BRIEFING | EMPTY_INPUT | NARRATOR_UNAVAILABLE | FAILED
    # 실패 사유를 한 가지로 뭉뚱그리지 않는다. 화면이 "다시 시도"를 권할지
    # "입력을 채우라"고 할지, 사유마다 다음 행동이 다르기 때문이다.
    status: str = "OK"
    disclaimer: str = DRAFT_DISCLAIMER
    notice_id: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


def generate_business_plan_draft(
    briefing_text: str,
    inputs: BusinessPlanInputs,
    *,
    notice_id: str | None = None,
    judgment_count: int = 0,
    flagged_clause_count: int = 0,
    narrate: Narrator | None = None,
) -> BusinessPlanDraft:
    """고정 목차 초안을 만든다. 확정된 결과는 무엇도 바꾸지 않는다.

    `briefing_text` 는 **코드가 확정한 결과를 렌더링한 텍스트**여야 한다. 이
    모듈은 그 텍스트를 검증할 방법이 없으므로, 근거의 품질은 호출부가 책임진다.
    `judgment_count` 와 `flagged_clause_count` 는 어떤 근거 위에서 쓴 초안인지
    되짚기 위한 기록이며, 생성 자체에는 쓰이지 않는다.
    """
    source = {
        "notice_id": notice_id,
        "judgment_count": judgment_count,
        "flagged_clause_count": flagged_clause_count,
    }

    def refuse(status: str, text: str) -> BusinessPlanDraft:
        return BusinessPlanDraft(
            text=text, status=status, notice_id=notice_id, source=source
        )

    # 근거 없이 쓴 초안은 이 기능에서 가장 나쁜 결과다. 모델을 부르기 전에 막는다.
    if not (briefing_text or "").strip():
        return refuse(
            "MISSING_BRIEFING",
            "검토 결과가 비어 있어 초안을 작성할 수 없습니다. 판정을 먼저 끝내 주세요.",
        )
    if not inputs.has_content():
        return refuse(
            "EMPTY_INPUT",
            "사업계획서에 반영할 회사 정보나 수행 방안을 한 가지 이상 입력해 주세요.",
        )
    if narrate is None:
        return refuse(
            "NARRATOR_UNAVAILABLE",
            "OPENAI_API_KEY가 설정되지 않아 사업계획서 초안을 생성할 수 없습니다.",
        )

    body = f"[검토 브리핑]\n{briefing_text}\n\n[사용자 입력]\n{inputs.render()}"
    try:
        generated = narrate(BUSINESS_PLAN_SYSTEM_PROMPT, body)
    except Exception as error:  # noqa: BLE001 - generation failure is an API result
        return refuse("FAILED", f"초안 생성 중 오류가 발생했습니다: {error}")

    cleaned = (generated or "").strip()
    if not cleaned:
        return refuse("FAILED", "모델이 빈 초안을 반환했습니다. 다시 시도해 주세요.")
    return BusinessPlanDraft(text=cleaned, notice_id=notice_id, source=source)
