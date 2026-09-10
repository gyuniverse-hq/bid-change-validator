from types import SimpleNamespace

from apps.api.app.document_rag.answer import (
    build_grounded_prompt,
    generate_grounded_answer,
)
from apps.api.app.document_rag.store import DocumentChunkHit, DocumentChunkMetadata


def _hit() -> DocumentChunkHit:
    return DocumentChunkHit(
        text="최근 3년간 1억원 이상의 수행실적을 보유한 업체",
        score=0.95,
        metadata=DocumentChunkMetadata(
            notice_id="notice-1",
            notice_version_id="version-1",
            version_number=1,
            document_id="doc-1",
            document_name="공고문.pdf",
            document_role="standard_notice",
            chunk_id="doc-1:CHUNK-0000",
            clause_label="제3조",
            page=3,
            source_locations=["p.3"],
        ),
    )


def test_build_grounded_prompt_contains_source_and_safety_instruction():
    messages = build_grounded_prompt("실적 조건이 뭐야?", [_hit()])

    assert messages[0]["role"] == "system"
    assert "참가 가능/불가를 독자적으로 판정하지 마세요" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "[S1]" in messages[1]["content"]
    assert "최근 3년간 1억원" in messages[1]["content"]


def test_generate_grounded_answer_returns_stable_citation_metadata():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="실적 조건은 1억원 이상입니다. [S1]"))]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: response)
        )
    )

    result = generate_grounded_answer(
        "실적 조건이 뭐야?",
        [_hit()],
        client=client,
        model="fake-model",
    )

    assert result.answer.endswith("[S1]")
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.ref == "S1"
    assert citation.document_id == "doc-1"
    assert citation.notice_version_id == "version-1"
    assert citation.page == 3
    assert citation.clause_label == "제3조"
