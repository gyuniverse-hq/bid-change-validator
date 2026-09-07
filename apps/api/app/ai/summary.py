"""Reading a notice back to the officer in plain prose.

This is the one place in the package where the model writes something a person
reads directly, and it is deliberately *not* a judgment. Nothing here decides
whether a term is acceptable or whether the company qualifies — it only says what
the notice is asking for, so an officer can tell at a glance whether the document
is worth their afternoon.

Because it is description rather than decision, the strict source-grounding used
by requirement extraction is not applied: there is no quote to verify against.
The system prompt carries the constraint instead — do not state facts the source
does not contain. That is a weaker guarantee, and it is why the output is labelled
as a summary everywhere it is shown, and why no downstream code reads it.

The prompt is kept as written in the original PoC. It was tuned against real
notices, and the sentence-style rules in it are the difference between prose an
officer will actually read and a bulleted restatement of the table of contents.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


# (system_prompt, user_body) -> free text. Deliberately not the structured
# extractor: a summary is prose, and forcing it through a JSON schema would only
# add a decode step that can fail.
Narrator = Callable[[str, str], str]

# How much source text is sent. A summary needs the shape of the document, not
# all of it, and the opening sections carry 사업개요·기간·예산·과업내용.
MAX_SOURCE_CHARS = 10_000

SYSTEM_PROMPT = """너는 나라장터 입찰공고 제안요청서(RFP) 본문을 담당자에게 구두로 설명하듯 풀어 말하는 도구다. 규칙:
1. 아래 원문에 실제로 적힌 내용만 담아라. 없는 사실(금액, 기간, 요건 등)을 지어내지 마라.
2. 충족 여부나 리스크를 판단하지 마라 — 판정이 아니라 내용 설명이다.
3. 목록·불릿·번호 매기기·소제목을 쓰지 마라. 사업개요, 사업기간, 사업예산, 주요 과업내용이
   자연스럽게 이어지는 하나의 글로, 4~6문장 정도로 풀어써라.
4. 문장 끝은 "~입니다", "~합니다" 같은 정중한 구어체 종결로 통일하고, 앞 문장과
   뒤 문장이 "이 사업은 ~입니다. 기간은 ~이며, ~을 목표로 합니다." 처럼 자연스럽게
   이어지게 하라. 개조식(명사로 끝맺는 딱딱한 문체)을 쓰지 마라."""


class NoticeSummary(BaseModel):
    """A summary, or an explicit statement of why there is none."""

    text: str | None = None
    status: str = "OK"  # OK | NO_SOURCE | NARRATOR_UNAVAILABLE | FAILED
    notes: str = ""

    @property
    def available(self) -> bool:
        return bool(self.text)


def source_text_from_chunks(chunks: list[dict[str, Any]], *, limit: int = MAX_SOURCE_CHARS) -> str:
    return "\n".join(chunk.get("text") or "" for chunk in chunks)[:limit]


def summarize_notice(
    source_text: str,
    *,
    title: str | None = None,
    narrate: Narrator | None = None,
) -> NoticeSummary:
    """Summarize notice text. Never raises; an absent summary is a stated result."""
    text = (source_text or "").strip()
    if not text:
        return NoticeSummary(status="NO_SOURCE", notes="요약할 본문이 없습니다.")
    if narrate is None:
        return NoticeSummary(
            status="NARRATOR_UNAVAILABLE",
            notes="요약 생성기가 주입되지 않았습니다 (OPENAI_API_KEY 미설정 등).",
        )

    user_body = f"[공고명]\n{title or ''}\n\n[RFP 본문]\n{text[:MAX_SOURCE_CHARS]}"
    try:
        written = narrate(SYSTEM_PROMPT, user_body)
    except Exception as error:  # noqa: BLE001 - reported, never propagated
        return NoticeSummary(status="FAILED", notes=f"요약 생성 실패: {error}")

    cleaned = (written or "").strip()
    if not cleaned:
        return NoticeSummary(status="FAILED", notes="요약 생성기가 빈 응답을 반환했습니다.")
    return NoticeSummary(text=cleaned)


def summarize_chunks(
    chunks: list[dict[str, Any]],
    *,
    title: str | None = None,
    narrate: Narrator | None = None,
) -> NoticeSummary:
    """Summarize the semantic chunks produced by `app.ai.chunking`."""
    return summarize_notice(source_text_from_chunks(chunks), title=title, narrate=narrate)


REPORT_NARRATIVE_SYSTEM = (
    "아래는 코드가 확정한 입찰공고 분석 리포트다. 판정을 바꾸거나 새 판정을 추가하지 마라. "
    "담당자에게 구두로 브리핑하듯, 목록·불릿·번호 매기기 없이 하나의 글로 이어지는 "
    "3~5문장으로 풀어써라. 문장 끝은 '~입니다', '~합니다' 같은 정중한 구어체로 통일하고, "
    "'참가자격은 ~이며, 확인이 필요한 조항은 ~입니다' 처럼 앞뒤 문장이 자연스럽게 이어지게 "
    "하라. 모든 수치는 리포트에 있는 그대로 사용하라."
)


def narrate_report(report_text: str, *, narrate: Narrator | None = None) -> NoticeSummary:
    """Read a finished report back as prose.

    Unlike `summarize_notice`, the input here is not source material — it is the
    verdicts code already reached. So the constraint is different and stricter:
    do not change a verdict, do not add one, and reuse the figures verbatim. The
    model is turning a table into sentences, nothing more.
    """
    text = (report_text or "").strip()
    if not text:
        return NoticeSummary(status="NO_SOURCE", notes="서술할 리포트 내용이 없습니다.")
    if narrate is None:
        return NoticeSummary(
            status="NARRATOR_UNAVAILABLE", notes="요약 서술 생략 — OPENAI_API_KEY 미설정"
        )
    try:
        written = narrate(REPORT_NARRATIVE_SYSTEM, text)
    except Exception as error:  # noqa: BLE001 - reported, never propagated
        return NoticeSummary(status="FAILED", notes=f"요약 서술 실패: {error}")

    cleaned = (written or "").strip()
    if not cleaned:
        return NoticeSummary(status="FAILED", notes="서술 생성기가 빈 응답을 반환했습니다.")
    return NoticeSummary(text=cleaned)
