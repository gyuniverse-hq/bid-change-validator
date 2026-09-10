from apps.api.app.ai.goldenset.fixtures import GoldenCase, GoldenDocument
from apps.api.app.ai.goldenset.scoring import score_case
from apps.api.app.ai.goldenset.spans import GoldenSpan


def _chunk(text: str, document_id: str, chunk_id: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "source_blocks": [{"document_id": document_id}],
    }


def test_span_labels_survive_whitespace_changes_and_reject_traps() -> None:
    case = GoldenCase(
        notice_no="N1",
        documents=(GoldenDocument("NOTICE", "unused", "NOTICE"),),
        spans=(
            GoldenSpan("P1", "NOTICE", "POSITIVE", "대기업 및 중견기업 참여 제한"),
            GoldenSpan("T1", "RFP", "TRAP", "입찰 참가자격이 제한됨"),
        ),
    )
    chunks = [
        _chunk("대기업및 중견기업  참여 제한", "NOTICE", "CHUNK-0000"),
        _chunk("누출 시 입찰 참가자격이 제한됨", "RFP", "CHUNK-0001"),
    ]

    report = score_case(case, chunks, [chunks[0]])

    assert report["chunk_health"]["span_containment"] == 1
    assert report["retrieval"]["recall"] == 1
    assert report["retrieval"]["precision"] == 1
    assert report["retrieval"]["trap_rate"] == 0


def test_funnel_marks_a_contained_but_unretrieved_span() -> None:
    case = GoldenCase(
        notice_no="N1",
        documents=(),
        spans=(GoldenSpan("P1", "NOTICE", "POSITIVE", "직접생산확인증명서"),),
    )
    chunks = [_chunk("직접 생산 확인 증명서", "NOTICE", "CHUNK-0000")]

    row = score_case(case, chunks, [])["funnel"][0]

    assert row == {
        "span_id": "P1",
        "note": "",
        "contained": True,
        "retrieved": False,
        "extracted": None,
        "canonical": None,
    }
