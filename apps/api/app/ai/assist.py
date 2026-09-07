"""The help desk: answering an officer's open questions about the current review.

"그래서 어떻게 해야 해?" is a real question and the pipeline has no answer for it.
Every other module produces a verdict per requirement; none of them explains what
to do next, and an officer staring at eleven UNKNOWN rows needs that more than an
eleventh reason string.

The rule that keeps this safe is narrow and absolute: **it never judges.** The
verdicts were already settled by `app.ai.judgment`, in code. This module receives
those settled results plus the profile the officer actually typed, and speaks
them back. It may explain, prioritise and advise; it may not decide.

The profile is included alongside the verdicts on purpose. Given only verdicts,
the assistant cannot answer "내가 방금 뭘 입력했더라" or notice that an answer is
already present in a field, and it deflects questions it should be able to
answer. Given both, it can point at the specific gap.

General questions — what 지체상금 is, how the tool works, plain small talk — are
answered from the model's own knowledge. Refusing those because they are not in
the case data makes the assistant useless for the thing people actually do with it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .clause_review.contracts import VERDICT_LABELS as CLAUSE_VERDICT_LABELS
from .clause_review.contracts import ClauseFinding
from .contracts import Judgment, QualificationRequirement
from .profile import as_profile_view
from .summary import Narrator


ASSIST_SYSTEM = """너는 나라장터 입찰 참가자격 검토를 돕는 도우미다. 이 화면에서 진행 중인
공고 검토를 돕는 게 주 업무지만, 그와 무관한 일반적인 질문(용어 설명, 절차 안내, 잡담,
이 도구 사용법 등)을 해도 자연스럽게 답한다 — 이런 질문까지 판정 정보가 없다는 이유로
답을 피하지 마라.

아래 [현재 상태]는 담당자가 지금까지 입력한 프로필 원문과, 코드가 그걸로 이미 확정한
판정 결과다. 규칙:
1. 이번 공고·프로필에 대한 충족/미충족/판정불가는 절대 새로 내리지 마라 — 이미 코드가
   정했다. [현재 상태]에 있는 그 결과를 있는 그대로 전달·설명만 하라.
2. [현재 상태]에 없는 이번 건의 구체적 사실(정확한 금액·날짜·인증 보유 여부 등)은
   지어내지 마라. 모르면 모른다고 하거나 프로필에 입력해 달라고 안내하라.
3. 반면 일반적인 지식(예: "하자보수가 뭐야?", "지체상금은 왜 있어?" 같은 용어·개념
   설명이나 잡담)은 이번 건 데이터와 무관해도 네가 아는 대로 자유롭게 답해도 된다.
4. 담당자가 "그래서 어떻게 해야 해?"처럼 막연하게 물으면 [현재 상태]를 근거로 다음
   행동을 구체적으로 안내하라.
5. 간결하고 대화하듯 자연스럽게 답하라. 질문 성격에 맞게 길이를 조절하라."""

_STATUS_LABELS = {"SATISFIED": "충족", "UNSATISFIED": "미충족", "UNKNOWN": "확인 불가"}

_NOTHING_ENTERED = "(아직 입력된 항목 없음)"


class AssistAnswer(BaseModel):
    text: str
    status: str = "OK"  # OK | EMPTY_QUESTION | NARRATOR_UNAVAILABLE | FAILED


def summarize_profile(profile: Any) -> str:
    """What the officer has actually filled in — not the verdicts drawn from it.

    Sending only the verdicts leaves the assistant unable to refer to the input
    itself, which is exactly what a vague question is usually about.
    """
    view = as_profile_view(profile)
    if not view:
        return _NOTHING_ENTERED

    lines: list[str] = []
    if view.company_name:
        lines.append(f"회사명: {view.company_name}")
    if view.region_label:
        lines.append(f"소재지: {view.region_label}")
    if view.company_size_label:
        lines.append(f"기업규모: {view.company_size_label}")
    if view.employee_count is not None:
        lines.append(f"임직원 수: {view.employee_count}명")
    if view.industry_labels:
        lines.append(f"업종: {', '.join(str(item) for item in view.industry_labels)}")
    if view.certification_labels():
        lines.append(f"보유 인증·면허: {', '.join(view.certification_labels())}")

    staff = view.staff
    if staff:
        known = [member for member in staff if member.career_years is not None]
        detail = (
            f", 최대 경력 {max(member.career_years or 0 for member in known):g}년"
            if known
            else ", 경력 정보 없음"
        )
        lines.append(f"인력: {len(staff)}명{detail}")

    performances = view.performances
    if performances:
        total = sum(item.amount or 0 for item in performances)
        lines.append(f"사업실적: {len(performances)}건, 합계 {total:,.0f}원")
    if view.fields:
        lines.append(f"사업 분야: {', '.join(view.fields)}")
    for key, entry in view.extensions.items():
        if entry.value is not None:
            lines.append(f"추가 항목 · {entry.label or key}: {entry.value}")

    return "\n".join(lines) if lines else _NOTHING_ENTERED


def summarize_state(
    *,
    profile: Any = None,
    judgments: list[Judgment] | None = None,
    requirements: list[QualificationRequirement] | None = None,
    clause_findings: list[ClauseFinding] | None = None,
    notice_title: str | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> str:
    """Render everything code has settled, as the assistant's only case facts."""
    requirement_by_key = {item.requirement_key: item for item in requirements or []}
    lines: list[str] = []

    if notice_title:
        lines.append(f"[검토 중인 공고]\n{notice_title}\n")

    lines.append("[담당자가 입력한 프로필]")
    lines.append(summarize_profile(profile))
    lines.append("")
    lines.append("[참가자격 판정 결과 — 코드가 확정함]")

    if not judgments:
        lines.append("- (아직 판정된 자격요건이 없습니다)")
    for judgment in judgments or []:
        requirement = requirement_by_key.get(judgment.requirement_key)
        source = (requirement.raw if requirement else judgment.requirement_key) or ""
        line = f"- [{_STATUS_LABELS[judgment.status]}] {source[:70]}: {judgment.reason}"
        if judgment.follow_up_question:
            line += f' (되묻기 대기 중: "{judgment.follow_up_question}")'
        if judgment.requires_evidence:
            line += " (증빙 미확인)"
        lines.append(line)

    flagged = [
        finding for finding in clause_findings or [] if finding.verdict == "NEEDS_REVIEW"
    ]
    if flagged:
        lines.append("")
        lines.append("[확인 필요 계약조항]")
        for finding in flagged:
            label = f"{finding.clause_label}항 " if finding.clause_label else ""
            lines.append(
                f"- {label}{finding.risk_type}"
                f"({CLAUSE_VERDICT_LABELS[finding.verdict]}): {finding.reason}"
            )

    if diagnostics:
        lines.append("")
        lines.append("[공고에서 확인된 제한·참고 사항]")
        for item in diagnostics:
            message = item.get("message")
            if message:
                lines.append(f"- {message}")

    return "\n".join(lines)


def answer_question(
    question: str,
    *,
    state_summary: str,
    narrate: Narrator | None = None,
) -> AssistAnswer:
    """Answer one question against already-settled state. Never raises."""
    text = (question or "").strip()
    if not text:
        return AssistAnswer(text="질문을 입력해 주세요.", status="EMPTY_QUESTION")
    if narrate is None:
        return AssistAnswer(
            text="OPENAI_API_KEY가 설정되지 않아 안내 도우미를 쓸 수 없습니다.",
            status="NARRATOR_UNAVAILABLE",
        )

    try:
        answer = narrate(
            ASSIST_SYSTEM, f"[현재 상태]\n{state_summary}\n\n[담당자 질문]\n{text}"
        )
    except Exception as error:  # noqa: BLE001 - a failed answer must not 500
        return AssistAnswer(
            text=f"응답 생성 중 오류가 발생했습니다: {error}", status="FAILED"
        )

    cleaned = (answer or "").strip()
    if not cleaned:
        return AssistAnswer(
            text="도우미가 빈 응답을 반환했습니다(모델 응답 없음) — 다시 시도해 주세요.",
            status="FAILED",
        )
    return AssistAnswer(text=cleaned)
