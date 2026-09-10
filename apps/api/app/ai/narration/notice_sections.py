"""주제별 공고 요약 — 전체 요약 하나로는 답이 안 되는 질문들을 위해.

`summary.summarize_notice()` 는 "이 공고가 뭔지" 까지만 답한다. 담당자가 실제로 하는
질문은 "제출서류가 뭐지", "평가는 어떻게 하지", "계약조건에 이상한 건 없나" 처럼
주제별이고, 12만 자짜리 제안요청서에서 그걸 사람이 찾는 것이 원래 이 도구를 만든
이유다.

역할 경계는 이 패키지의 다른 곳과 같다. 모델은 **서술만** 하고 판정하지 않는다.
요약은 원문 문자열 대조가 불가능한 산문이라 요건 추출 같은 `raw` 대조 보증을 걸 수
없다 — 대신 어떤 청크를 근거로 삼았는지 `chunk_ids` 로 남겨서 담당자가 원문을
직접 확인할 수 있게 한다. 그래서 화면에서도 요약 옆에 근거 링크가 같이 나가야 한다.

주제 어휘는 `apps/api/app/scripts/product_golden_inspector.py` 의 `KEYWORDS` 와 맞춰
두었다. 그 모듈은 `SessionLocal`·`models` 를 import 해서 ORM 에 묶여 있어 여기서
가져다 쓸 수 없으므로 다시 적는다 — 한쪽을 고치면 다른 쪽도 봐야 한다. 개요·일정은
요약에만 필요해서 여기서 추가한 항목이다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field


NoticeSectionTopic = Literal[
    "OVERVIEW",
    "QUALIFICATION",
    "SCOPE",
    "SUBMISSION",
    "EVALUATION",
    "CONTRACT",
    "SCHEDULE",
]

SECTION_TOPICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "OVERVIEW": (
        "사업 개요",
        ("사업명", "사업기간", "사업예산", "추정가격", "사업개요", "용역명", "배정예산"),
    ),
    "QUALIFICATION": (
        "참가자격",
        ("참가자격", "입찰참가자격", "자격요건", "등록", "면허", "실적", "인력", "지역"),
    ),
    "SCOPE": (
        "과업 내용",
        ("과업", "요구사항", "산출물", "수행", "구축", "개발", "범위"),
    ),
    "SUBMISSION": (
        "제출 서류",
        ("제출서류", "구비서류", "증빙", "서식", "제출", "제안서"),
    ),
    "EVALUATION": (
        "평가 방법",
        ("평가", "배점", "정량", "정성", "발표", "협상", "심사"),
    ),
    "CONTRACT": (
        "계약 조건",
        ("계약", "대금", "보증", "지체상금", "하자", "검수", "저작권", "지식재산권"),
    ),
    "SCHEDULE": (
        "일정",
        ("일정", "마감", "개찰", "설명회", "접수기간", "제출기한"),
    ),
}

# 주제 하나에 보낼 최대 분량과 전체 상한. 12만 자 문서를 통째로 보낼 수는 없고,
# 주제마다 상한을 따로 두어야 분량이 큰 과업내용이 나머지를 밀어내지 않는다.
MAX_TOPIC_CHARS = 2_500
MAX_BODY_CHARS = 14_000

StructuredExtractor = Callable[[str, str, dict[str, Any]], dict[str, Any]]

SECTION_SCHEMA: dict[str, Any] = {
    "name": "notice_sections",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "topic": {
                            "type": "string",
                            "enum": list(SECTION_TOPICS),
                            "description": "요약 대상 주제",
                        },
                        "summary": {
                            "type": ["string", "null"],
                            "description": (
                                "그 주제에 대해 제공된 텍스트에 실제로 적힌 내용만 "
                                "2~4문장으로 풀어쓴다. 근거가 없으면 null. 지어내지 마라."
                            ),
                        },
                    },
                    "required": ["topic", "summary"],
                },
            }
        },
        "required": ["sections"],
    },
}

SYSTEM_PROMPT = """너는 나라장터 입찰공고를 주제별로 담당자에게 설명하는 도구다. 규칙:
1. 각 주제마다 **제공된 텍스트에 실제로 적힌 내용만** 담아라. 없는 사실을 지어내지 마라.
2. 제공된 텍스트에 그 주제 내용이 없으면 summary를 null로 두어라. 빈 문자열이나
   "정보 없음" 같은 문장을 쓰지 마라.
3. 충족 여부나 리스크를 판단하지 마라 — 판정이 아니라 내용 설명이다.
4. 주제당 2~4문장. 목록·불릿·번호 매기기를 쓰지 말고 이어지는 하나의 글로 써라.
5. 문장 끝은 "~입니다", "~합니다" 로 통일하라. 개조식(명사로 끝맺는 문체)을 쓰지 마라.
6. 금액·기간·비율은 원문 표기를 그대로 옮겨라. 단위를 바꾸거나 계산하지 마라."""


class NoticeSection(BaseModel):
    """한 주제의 요약과 그 근거가 된 청크."""

    topic: str
    label: str
    summary: str
    chunk_ids: list[str] = Field(default_factory=list)


class NoticeSectionSummary(BaseModel):
    """주제별 요약 결과, 또는 없는 이유."""

    sections: list[NoticeSection] = Field(default_factory=list)
    status: str = "OK"  # OK | NO_SOURCE | EXTRACTOR_UNAVAILABLE | FAILED
    notes: str = ""

    @property
    def available(self) -> bool:
        return bool(self.sections)

    def by_topic(self) -> dict[str, NoticeSection]:
        return {section.topic: section for section in self.sections}


def select_topic_chunks(
    chunks: list[dict[str, Any]], *, max_chars_per_topic: int = MAX_TOPIC_CHARS
) -> dict[str, list[dict[str, Any]]]:
    """주제별로 관련 청크를 고른다. 키워드 빈도 순으로 뽑고 주제마다 분량 상한.

    한 청크가 두 주제에 들어가는 것은 막지 않는다 — 계약조건과 과업내용이 한 문단에
    같이 있는 공고가 흔하고, 억지로 하나에만 배정하면 다른 쪽 요약이 근거를 잃는다.
    """
    selected: dict[str, list[dict[str, Any]]] = {}
    position = {id(chunk): order for order, chunk in enumerate(chunks)}

    for topic, (_label, keywords) in SECTION_TOPICS.items():
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for order, chunk in enumerate(chunks):
            text = chunk.get("text") or ""
            if not text.strip():
                continue
            score = sum(text.count(keyword) for keyword in keywords)
            if score:
                scored.append((score, order, chunk))

        # 점수 내림차순으로 고르되, 동점이면 문서 순서를 지킨다.
        scored.sort(key=lambda item: (-item[0], item[1]))

        picked: list[dict[str, Any]] = []
        used = 0
        for _score, _order, chunk in scored:
            text = chunk.get("text") or ""
            if picked and used + len(text) > max_chars_per_topic:
                break
            picked.append(chunk)
            used += len(text)

        if picked:
            # 모델에게는 문서 순서대로 보여준다. 점수 순으로 뒤섞인 글을 요약하면
            # 앞뒤가 끊긴 문장이 나온다.
            picked.sort(key=lambda chunk: position[id(chunk)])
            selected[topic] = picked

    return selected


def build_body(
    topic_chunks: dict[str, list[dict[str, Any]]], *, max_chars: int = MAX_BODY_CHARS
) -> str:
    parts: list[str] = []
    for topic, picked in topic_chunks.items():
        label = SECTION_TOPICS[topic][0]
        body = "\n".join(chunk.get("text") or "" for chunk in picked)
        parts.append(f"[주제 {topic} · {label}]\n{body}")
    return "\n\n".join(parts)[:max_chars]


def summarize_sections(
    chunks: list[dict[str, Any]],
    *,
    structured_extract: StructuredExtractor | None = None,
    title: str | None = None,
) -> NoticeSectionSummary:
    """공고를 주제별로 요약한다. 예외를 올리지 않는다.

    구조화 출력을 쓰는 이유는 주제와 요약을 짝지어 받기 위해서지 값을 검증하기
    위해서가 아니다. 검증은 근거를 보낸 주제만 남기는 것으로 대신한다.
    """
    if not chunks:
        return NoticeSectionSummary(status="NO_SOURCE", notes="요약할 본문이 없습니다.")

    topic_chunks = select_topic_chunks(chunks)
    if not topic_chunks:
        return NoticeSectionSummary(
            status="NO_SOURCE", notes="주제에 해당하는 본문을 찾지 못했습니다."
        )
    if structured_extract is None:
        return NoticeSectionSummary(
            status="EXTRACTOR_UNAVAILABLE",
            notes="구조화 추출기가 주입되지 않았습니다 (OPENAI_API_KEY 미설정 등).",
        )

    user_body = f"[공고명]\n{title or ''}\n\n{build_body(topic_chunks)}"
    try:
        extracted = structured_extract(SYSTEM_PROMPT, user_body, SECTION_SCHEMA)
    except Exception as error:  # noqa: BLE001 - 결과로 보고하고 전파하지 않는다
        return NoticeSectionSummary(status="FAILED", notes=f"세부 요약 생성 실패: {error}")

    sections: list[NoticeSection] = []
    for item in extracted.get("sections") or []:
        topic = str(item.get("topic") or "")
        summary = (item.get("summary") or "").strip()
        # 근거를 보내지 않은 주제의 요약은 버린다. 모델이 스키마의 enum 을 보고
        # 본 적 없는 주제까지 채워 넣는 일이 있는데, 그건 지어낸 것이다.
        if not summary or topic not in topic_chunks:
            continue
        sections.append(
            NoticeSection(
                topic=topic,
                label=SECTION_TOPICS[topic][0],
                summary=summary,
                chunk_ids=[
                    chunk["chunk_id"]
                    for chunk in topic_chunks[topic]
                    if chunk.get("chunk_id")
                ],
            )
        )

    if not sections:
        return NoticeSectionSummary(
            status="FAILED", notes="주제별 요약이 생성되지 않았습니다."
        )

    order = list(SECTION_TOPICS)
    sections.sort(key=lambda section: order.index(section.topic))
    return NoticeSectionSummary(sections=sections)
