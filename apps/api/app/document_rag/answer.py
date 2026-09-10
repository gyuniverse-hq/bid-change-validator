"""Grounded answer generation over retrieved notice-document chunks."""

from __future__ import annotations

import os
import re
from typing import Any

from pydantic import BaseModel, Field

from .store import DocumentChunkHit


DEFAULT_CHAT_MODEL = "gpt-5.6-luna"


class GroundedCitation(BaseModel):
    ref: str
    document_id: str
    document_name: str
    notice_version_id: str
    chunk_id: str
    clause_label: str | None = None
    page: int | None = None
    source_locations: list[str] = Field(default_factory=list)
    quote: str


class GroundedDocumentAnswer(BaseModel):
    answer: str
    # Only refs used in the answer, deduplicated in first-appearance order.
    citations: list[GroundedCitation] = Field(default_factory=list)
    # All input hits, retaining retrieval rank and their original source metadata.
    sources: list[GroundedCitation] = Field(default_factory=list)


def build_grounded_prompt(question: str, hits: list[DocumentChunkHit]) -> list[dict[str, str]]:
    """Render a LangChain prompt while keeping OpenAI SDK calls project-native."""

    if len({hit.metadata.notice_version_id for hit in hits}) > 1:
        raise ValueError("grounded answer cannot mix notice versions")

    try:
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError as error:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("Document RAG requires `langchain-core`") from error

    context_parts: list[str] = []
    for index, hit in enumerate(hits, start=1):
        metadata = hit.metadata
        location = ", ".join(metadata.source_locations)
        if not location and metadata.page is not None:
            location = f"p.{metadata.page}"
        context_parts.append(
            f"[S{index}] document={metadata.document_name}; "
            f"clause={metadata.clause_label or '정보 없음'}; "
            f"location={location or '위치 정보 없음'}; "
            f"notice_version_id={metadata.notice_version_id}\n{hit.text}"
        )

    context = "\n\n".join(context_parts) or "검색된 근거가 없습니다."
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "당신은 나라장터 입찰 공고 문서의 근거를 설명하는 AI입니다. "
                "제공된 SOURCE 밖의 사실을 공고 근거처럼 만들지 마세요. "
                "참가 가능/불가를 독자적으로 판정하지 마세요. "
                "질문에 답할 근거가 부족하면 확인할 수 없다고 명시하세요. "
                "실제로 사용한 SOURCE만 [S1] 형식으로 인용하세요. "
                "여러 SOURCE를 사용하면 [S1] [S2]처럼 각각 표시하세요. "
                "제공되지 않은 Source ID를 생성하지 마세요. "
                "근거가 없으면 억지로 인용을 생성하지 마세요.",
            ),
            (
                "human",
                "질문:\n{question}\n\nSOURCE:\n{context}\n\n"
                "근거에 기반해 간결하게 답변하세요.",
            ),
        ]
    )
    rendered = prompt.invoke({"question": question, "context": context})

    messages: list[dict[str, str]] = []
    for message in rendered.to_messages():
        role = "system" if message.type == "system" else "user"
        messages.append({"role": role, "content": str(message.content)})
    return messages


def generate_grounded_answer(
    question: str,
    hits: list[DocumentChunkHit],
    *,
    api_key: str | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> GroundedDocumentAnswer:
    """Return all sources separately from explicit [S#] citations in the answer."""

    if not question.strip():
        raise ValueError("question must not be blank")

    messages = build_grounded_prompt(question, hits)
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("Document RAG requires the `openai` package") from error
        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=resolved_key)

    response = client.chat.completions.create(
        model=model or os.getenv("OPENAI_MODEL_DEFAULT") or DEFAULT_CHAT_MODEL,
        messages=messages,
    )
    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError("OpenAI response did not contain any choices")
    content = getattr(choices[0].message, "content", None)
    if not content:
        raise RuntimeError("OpenAI grounded answer returned empty content")

    sources = [
        GroundedCitation(
            ref=f"S{index}",
            document_id=hit.metadata.document_id,
            document_name=hit.metadata.document_name,
            notice_version_id=hit.metadata.notice_version_id,
            chunk_id=hit.metadata.chunk_id,
            clause_label=hit.metadata.clause_label,
            page=hit.metadata.page,
            source_locations=hit.metadata.source_locations,
            quote=hit.text,
        )
        for index, hit in enumerate(hits, start=1)
    ]
    answer = str(content)
    refs = list(dict.fromkeys(re.findall(r"\[(S[0-9]+)\]", answer)))
    by_ref = {source.ref: source for source in sources}
    unknown_refs = [ref for ref in refs if ref not in by_ref]
    if unknown_refs:
        raise ValueError(f"answer cites unknown source refs: {', '.join(unknown_refs)}")
    return GroundedDocumentAnswer(
        answer=answer,
        citations=[by_ref[ref] for ref in refs],
        sources=sources,
    )
