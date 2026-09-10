"""판정 결과·근거 조항·공고 요약을 한 브리핑으로 묶고, 그 위에서 답하게 한다.

담당자가 화면에서 보는 것은 결국 세 가지다 — 우리가 적격인가, 왜 그렇게 판단했는가,
이 공고가 대체 뭘 요구하는가. 지금은 그 셋이 서로 다른 모듈에서 따로 나오고,
화면이 알아서 이어붙여야 한다. 이 모듈이 그 조립을 맡는다.

**지켜야 하는 경계가 하나 있다.** 여기서 모델이 하는 일은 이미 확정된 것을 문장으로
풀어쓰는 것뿐이다. 충족/미충족은 `app.ai.judgment` 가 코드로 정했고, 조항 위험은
`app.ai.clause_review` 가 예규 원문과 대조해 정했다. 브리핑도 챗봇도 그 결과를
바꾸거나 새로 만들지 않는다 — 모델에게 넘어가는 것은 `render_briefing_text()` 가
만든 **확정된 사실과 원문 인용뿐**이고, 그 밖의 것은 모른다고 답해야 한다.

`Judgment` 에는 사람이 읽을 사유 문장이 없다(`reason_code` 만 있다). 그래서 사유는
여기서 **코드로** 만든다 — 모델에게 사유를 지어내게 하면 판정과 설명이 어긋난다.
Backend 에 `reason` 필드가 생기면(docs/llm-rag/02-integration-requests.md A-2)
그 값을 우선 쓰도록 바꾸면 된다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .analysis_result import AnalysisDiagnostic, RequirementAnalysisResult
from .clause_review.contracts import VERDICT_LABELS as CLAUSE_VERDICT_LABELS
from .clause_review.contracts import ClauseFinding, apply_overlapping_categories
from .contracts import Evidence, Judgment, QualificationRequirement
from .notice_digest import NoticeDigest
from .summary import Narrator, NoticeSummary, narrate_report


STATUS_LABELS = {"SATISFIED": "충족", "UNSATISFIED": "미충족", "UNKNOWN": "확인 불가"}

OVERALL_LABELS = {
    "eligible": "적격",
    "ineligible": "부적격",
    "insufficient_data": "확인 필요",
}

# 판정 사유는 코드가 만든다. reason_code 는 기계용 값이라 그대로 화면에 내면
# 담당자가 읽을 수 없고, 모델에게 문장을 맡기면 판정과 설명이 어긋날 수 있다.
REASON_LABELS = {
    "RULE_MATCH": "회사 프로필이 요건을 충족합니다",
    "RULE_MISMATCH": "회사 프로필이 요건에 미치지 못합니다",
    "INSUFFICIENT_DATA": "판정에 필요한 프로필 정보가 없습니다",
    "NEEDS_REVIEW": "자동 판정으로 확정할 수 없어 담당자 확인이 필요합니다",
    "UNSUPPORTED_REQUIREMENT": "자동 판정을 지원하지 않는 유형입니다",
}

BASIS_LABELS = {
    "PROFILE": "회사 프로필",
    "USER_ANSWER": "담당자 답변",
    "NONE": "근거 없음",
}


class EvidenceQuote(BaseModel):
    """판정 근거가 된 공고 원문 한 조각."""

    evidence_key: str
    quote: str
    location: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None


class JudgmentBrief(BaseModel):
    """요건 하나에 대한 판정과 그 근거."""

    requirement_key: str
    requirement_type: str | None = None
    requirement_raw: str = ""
    status: str
    status_label: str
    reason_code: str
    reason: str
    basis: str
    requires_evidence: bool = False
    profile_refs: list[dict[str, str]] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class NoticeFactBrief(BaseModel):
    """판정하지 않고 기록만 한 공고 사실."""

    code: str
    message: str
    raw: str = ""
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class NoticeBriefing(BaseModel):
    """화면과 챗봇이 함께 쓰는 하나의 브리핑."""

    notice_id: str | None = None
    notice_version_id: str | None = None
    title: str | None = None
    overall_status: str | None = None
    overall_label: str | None = None
    judgments: list[JudgmentBrief] = Field(default_factory=list)
    notice_facts: list[NoticeFactBrief] = Field(default_factory=list)
    clause_findings: list[ClauseFinding] = Field(default_factory=list)
    digest: NoticeDigest | None = None

    def counts(self) -> dict[str, int]:
        tally = {"SATISFIED": 0, "UNSATISFIED": 0, "UNKNOWN": 0}
        for item in self.judgments:
            tally[item.status] = tally.get(item.status, 0) + 1
        return tally

    def flagged_clauses(self) -> list[ClauseFinding]:
        return [item for item in self.clause_findings if item.verdict == "NEEDS_REVIEW"]


def _quote(evidence: Evidence) -> EvidenceQuote:
    return EvidenceQuote(
        evidence_key=evidence.evidence_key,
        quote=evidence.quote,
        location=evidence.location.display,
        document_id=evidence.document_id,
        chunk_id=evidence.chunk_id,
    )


def _reason_for(judgment: Judgment) -> str:
    """코드가 확정한 판정에 대한 읽을 수 있는 사유.

    Backend 의 `Judgment` 에 `reason` 필드가 생기면 그 값을 먼저 쓴다. 지금은
    reason_code 를 옮기고, 증빙 미확인처럼 담당자가 반드시 알아야 하는 조건을 덧붙인다.
    """
    supplied = getattr(judgment, "reason", "") or ""
    if supplied:
        return supplied

    reason = REASON_LABELS.get(judgment.reason_code, judgment.reason_code)
    if judgment.status == "SATISFIED" and judgment.requires_evidence:
        reason += " (증빙 서류 미확인 — 제출 전 확인 필요)"
    if judgment.basis_type == "USER_ANSWER":
        reason += " (담당자 답변에 근거)"
    return reason


def build_briefing(
    *,
    judgments: list[Judgment],
    requirements: list[QualificationRequirement] | None = None,
    evidence: list[Evidence] | None = None,
    diagnostics: list[AnalysisDiagnostic] | None = None,
    clause_findings: list[ClauseFinding] | None = None,
    digest: NoticeDigest | None = None,
    overall_status: str | None = None,
    notice_id: str | None = None,
    notice_version_id: str | None = None,
    title: str | None = None,
) -> NoticeBriefing:
    """확정된 결과들을 하나의 브리핑으로 조립한다. 여기서 판정하지 않는다."""
    requirement_by_key = {item.requirement_key: item for item in requirements or []}
    evidence_by_key = {item.evidence_key: item for item in evidence or []}

    briefs: list[JudgmentBrief] = []
    for judgment in judgments:
        requirement = requirement_by_key.get(judgment.requirement_key)
        quotes = [
            _quote(evidence_by_key[key])
            for key in judgment.requirement_evidence_keys
            if key in evidence_by_key
        ]
        # 판정에 근거 키가 안 붙어 있으면 요건 쪽 근거를 따라간다. 요건과 판정은
        # requirement_key 로 이어져 있으므로 같은 근거를 가리킨다.
        if not quotes and requirement is not None:
            quotes = [
                _quote(evidence_by_key[key])
                for key in requirement.evidence_keys
                if key in evidence_by_key
            ]

        briefs.append(
            JudgmentBrief(
                requirement_key=judgment.requirement_key,
                requirement_type=requirement.type if requirement else None,
                requirement_raw=requirement.raw if requirement else "",
                status=judgment.status,
                status_label=STATUS_LABELS.get(judgment.status, judgment.status),
                reason_code=judgment.reason_code,
                reason=_reason_for(judgment),
                basis=BASIS_LABELS.get(judgment.basis_type, judgment.basis_type),
                requires_evidence=judgment.requires_evidence,
                profile_refs=list(judgment.profile_refs),
                evidence=quotes,
            )
        )

    facts: list[NoticeFactBrief] = []
    for diagnostic in diagnostics or []:
        if diagnostic.kind != "NOTICE_FACT":
            continue
        facts.append(
            NoticeFactBrief(
                code=diagnostic.code,
                message=diagnostic.message,
                raw=str(diagnostic.details.get("raw") or ""),
                evidence=[
                    _quote(evidence_by_key[key])
                    for key in diagnostic.evidence_keys
                    if key in evidence_by_key
                ],
            )
        )

    return NoticeBriefing(
        notice_id=notice_id,
        notice_version_id=notice_version_id,
        title=title,
        overall_status=overall_status,
        overall_label=OVERALL_LABELS.get(overall_status or "", overall_status),
        judgments=briefs,
        notice_facts=facts,
        clause_findings=apply_overlapping_categories(list(clause_findings or [])),
        digest=digest,
    )


def build_briefing_from_analysis(
    analysis: RequirementAnalysisResult,
    judgments: list[Judgment],
    **kwargs: Any,
) -> NoticeBriefing:
    """분석 결과를 그대로 받아 브리핑을 만든다."""
    kwargs.setdefault("notice_id", analysis.notice_id)
    kwargs.setdefault("notice_version_id", analysis.notice_version_id)
    return build_briefing(
        judgments=judgments,
        requirements=analysis.requirements,
        evidence=analysis.evidence,
        diagnostics=analysis.diagnostics,
        **kwargs,
    )


# 인용 길이 상한. 근거 조항 전체를 통째로 넣으면 브리핑 본문이 원문 사본이 된다.
MAX_QUOTE_CHARS = 220


def _clip(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    collapsed = " ".join((text or "").split())
    return collapsed[:limit] + ("…" if len(collapsed) > limit else "")


def render_briefing_text(briefing: NoticeBriefing) -> str:
    """브리핑을 평문으로 렌더링한다.

    화면에 쓰는 텍스트이자 **모델에게 넘기는 유일한 사실 출처**다. 여기 없는 것은
    모델도 모르는 것이어야 한다. 그래서 판정·사유·근거 인용을 전부 담되, 판정을
    유도하는 해석은 넣지 않는다.
    """
    lines: list[str] = []

    if briefing.title:
        lines.append(f"[공고] {briefing.title}")
    if briefing.notice_id:
        lines.append(f"  공고번호: {briefing.notice_id}")

    if briefing.digest and briefing.digest.overview.available:
        lines.append("")
        lines.append("[공고 개요]")
        lines.append(f"  {briefing.digest.overview.text}")

    if briefing.digest and briefing.digest.sections.available:
        lines.append("")
        lines.append("[공고 세부 내용]")
        for section in briefing.digest.sections.sections:
            lines.append(f"  · {section.label}: {section.summary}")

    tally = briefing.counts()
    lines.append("")
    lines.append(f"[참가자격 판정] {briefing.overall_label or '(집계 없음)'}")
    lines.append(
        f"  충족 {tally['SATISFIED']} / 미충족 {tally['UNSATISFIED']} / "
        f"확인 불가 {tally['UNKNOWN']}"
    )
    if not briefing.judgments:
        lines.append("  (판정된 자격요건이 없습니다)")

    for item in briefing.judgments:
        lines.append("")
        lines.append(f"  [{item.status_label}] {_clip(item.requirement_raw, 90)}")
        lines.append(f"      사유: {item.reason}")
        lines.append(f"      근거 기준: {item.basis}")
        for quote in item.evidence:
            where = f" ({quote.location})" if quote.location else ""
            lines.append(f"      공고 원문{where}: “{_clip(quote.quote)}”")

    if briefing.notice_facts:
        lines.append("")
        lines.append("[확인했으나 판정 대상이 아닌 사항]")
        for fact in briefing.notice_facts:
            lines.append(f"  · {_clip(fact.raw, 120)}")

    flagged = briefing.flagged_clauses()
    if flagged:
        lines.append("")
        lines.append(f"[확인 필요 계약조항] {len(flagged)}건")
        for finding in flagged:
            label = f"{finding.clause_label}항 " if finding.clause_label else ""
            lines.append(
                f"  · {label}{finding.label}"
                f"({CLAUSE_VERDICT_LABELS[finding.verdict]}): {finding.reason}"
            )
            if finding.matched_text:
                lines.append(f"      공고 원문: “{_clip(finding.matched_text)}”")
            if finding.standard and finding.standard.clause_ref:
                lines.append(
                    f"      표준: {finding.standard.description}"
                    f" ({finding.standard.clause_ref})"
                )

    return "\n".join(lines)


def narrate_briefing(
    briefing: NoticeBriefing, *, narrate: Narrator | None = None
) -> NoticeSummary:
    """브리핑을 담당자에게 구두로 설명하듯 풀어쓴다. 판정은 바꾸지 않는다."""
    return narrate_report(render_briefing_text(briefing), narrate=narrate)


CHAT_SYSTEM_PROMPT = """너는 나라장터 입찰 참가자격 검토를 돕는 도우미다. 이 화면에서 진행 중인
공고 검토를 돕는 게 주 업무지만, 그와 무관한 일반적인 질문(용어 설명, 절차 안내,
이 도구 사용법 등)을 해도 자연스럽게 답한다 — 이런 질문까지 검토 정보가 없다는
이유로 답을 피하지 마라.

아래 [현재 상태]는 코드가 이미 확정한 판정 결과와 그 근거가 된 공고 원문이다. 규칙:
1. 이번 공고에 대한 충족/미충족/확인 불가를 절대 새로 내리지 마라 — 이미 코드가
   정했다. [현재 상태]에 있는 결과를 있는 그대로 전달·설명만 하라.
2. [현재 상태]에 없는 이번 건의 구체적 사실(정확한 금액·날짜·자격 보유 여부 등)은
   지어내지 마라. 모르면 모른다고 하거나 어디를 확인해야 하는지 안내하라.
3. 근거를 물으면 [현재 상태]에 인용된 공고 원문을 그대로 보여주며 설명하라.
4. 반면 일반적인 지식(예: "하자보수가 뭐야?", "지체상금은 왜 있어?" 같은 용어·개념
   설명)은 이번 건 데이터와 무관해도 네가 아는 대로 자유롭게 답해도 된다.
5. 담당자가 "그래서 어떻게 해야 해?"처럼 막연하게 물으면 [현재 상태]를 근거로 다음
   행동을 구체적으로 안내하라.
6. 간결하고 대화하듯 자연스럽게 답하라. 질문 성격에 맞게 길이를 조절하라."""


class ChatAnswer(BaseModel):
    text: str
    status: str = "OK"  # OK | EMPTY_QUESTION | NARRATOR_UNAVAILABLE | FAILED


def answer_question(
    question: str,
    briefing: NoticeBriefing,
    *,
    narrate: Narrator | None = None,
    history: list[tuple[str, str]] | None = None,
) -> ChatAnswer:
    """브리핑을 근거로 담당자 질문에 답한다. 예외를 올리지 않는다.

    `history` 는 (질문, 답변) 쌍이다. 앞선 대화를 넣어야 "그럼 그건 왜?" 같은
    이어지는 질문에 답할 수 있다.
    """
    text = (question or "").strip()
    if not text:
        return ChatAnswer(text="질문을 입력해 주세요.", status="EMPTY_QUESTION")
    if narrate is None:
        return ChatAnswer(
            text="OPENAI_API_KEY가 설정되지 않아 안내 도우미를 쓸 수 없습니다.",
            status="NARRATOR_UNAVAILABLE",
        )

    parts = [f"[현재 상태]\n{render_briefing_text(briefing)}"]
    for asked, answered in history or []:
        parts.append(f"[이전 질문]\n{asked}\n\n[이전 답변]\n{answered}")
    parts.append(f"[담당자 질문]\n{text}")

    try:
        answer = narrate(CHAT_SYSTEM_PROMPT, "\n\n".join(parts))
    except Exception as error:  # noqa: BLE001 - 답변 실패가 화면을 깨뜨리면 안 된다
        return ChatAnswer(
            text=f"응답 생성 중 오류가 발생했습니다: {error}", status="FAILED"
        )

    cleaned = (answer or "").strip()
    if not cleaned:
        return ChatAnswer(
            text="도우미가 빈 응답을 반환했습니다 — 다시 시도해 주세요.", status="FAILED"
        )
    return ChatAnswer(text=cleaned)
