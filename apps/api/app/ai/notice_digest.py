"""공고 요약 한 번에 — 전체 개요 + 주제별 세부.

호출하는 쪽이 알아야 할 것을 하나로 줄인다. 전체 요약은 산문 생성기(Narrator)를,
주제별 요약은 구조화 추출기를 쓰는데, 둘 다 없으면 없는 대로, 하나만 있으면 그것만
만들어 돌려준다. 어느 쪽도 예외를 올리지 않는다.

두 요약이 하는 일이 다르다:

- 개요(overview) — "이 공고가 뭔지" 를 4~6문장으로. 목록을 훑을 때 읽는다.
- 세부(sections) — "제출서류가 뭐지", "계약조건에 이상한 건 없나" 처럼 주제별 질문에
  답한다. 각 항목은 근거 청크를 달고 다닌다.

둘 다 **판정이 아니다.** 충족 여부는 `app.ai.judgment` 가, 조항 위험은
`app.ai.clause_review` 가 코드로 정한다. 여기서 나온 문장은 어떤 판정에도 입력되지
않으며, 화면에서도 요약이라고 표시되어야 한다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .notice_sections import (
    NoticeSectionSummary,
    StructuredExtractor,
    summarize_sections,
)
from .summary import MAX_SOURCE_CHARS, Narrator, NoticeSummary, summarize_notice


class NoticeDigest(BaseModel):
    """한 공고에 대한 요약 묶음."""

    notice_id: str | None = None
    notice_version_id: str | None = None
    title: str | None = None
    overview: NoticeSummary = Field(default_factory=NoticeSummary)
    sections: NoticeSectionSummary = Field(default_factory=NoticeSectionSummary)

    @property
    def available(self) -> bool:
        return self.overview.available or self.sections.available


def build_notice_digest(
    chunks: list[dict[str, Any]],
    *,
    title: str | None = None,
    notice_id: str | None = None,
    notice_version_id: str | None = None,
    narrate: Narrator | None = None,
    structured_extract: StructuredExtractor | None = None,
    overview_source_chars: int = MAX_SOURCE_CHARS,
) -> NoticeDigest:
    """전체 요약과 주제별 요약을 함께 만든다.

    개요는 문서 앞부분을 그대로 읽힌다 — 사업개요·기간·예산이 대개 거기 있고,
    주제별로 고른 조각을 이어붙이면 흐름이 끊긴 글이 나온다. 세부 요약은 반대로
    주제별로 골라 보내야 하므로 서로 다른 입력을 쓴다.
    """
    overview_source = "\n".join(chunk.get("text") or "" for chunk in chunks)[
        :overview_source_chars
    ]

    return NoticeDigest(
        notice_id=notice_id,
        notice_version_id=notice_version_id,
        title=title,
        overview=summarize_notice(overview_source, title=title, narrate=narrate),
        sections=summarize_sections(
            chunks, structured_extract=structured_extract, title=title
        ),
    )
