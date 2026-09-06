from apps.api.app.ai.backend_blocks import canonical_source_blocks
from apps.api.app.ai.chunking import chunk_source_blocks
from apps.api.app.ai.requirement_extraction import (
    extract_legacy_slots,
    select_eligibility_chunks,
    validate_extracted_slot,
)


def _chunks():
    blocks = canonical_source_blocks(
        document_id="doc-1",
        text_sha256="sha",
        blocks=[
            {
                "block_index": 0,
                "page": 3,
                "location": "p.3",
                "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 5억원 이상\n3.2 서울 소재 업체",
            },
            {
                "block_index": 1,
                "page": 4,
                "location": "p.4",
                "text": "4. 제출서류\n실적증명서 제출",
            },
        ],
    )
    return chunk_source_blocks(blocks)


def test_select_eligibility_section_includes_children_until_next_top_level():
    selected = select_eligibility_chunks(_chunks())

    assert [chunk["clause_label"] for chunk in selected] == ["3", "3.1", "3.2"]


def test_select_eligibility_section_does_not_cross_backend_document_boundary():
    doc_a = canonical_source_blocks(
        document_id="doc-a",
        text_sha256="sha-a",
        blocks=[
            {
                "block_index": 0,
                "page": 1,
                "location": "p.1",
                "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 5억원 이상",
            }
        ],
    )
    doc_b = canonical_source_blocks(
        document_id="doc-b",
        text_sha256="sha-b",
        blocks=[
            {
                "block_index": 0,
                "page": 1,
                "location": "p.1",
                "text": "이 문장은 다른 문서의 서두이며 자격요건이 아니다.",
            }
        ],
    )

    chunks = chunk_source_blocks(doc_a)
    offset = len(chunks)
    for index, chunk in enumerate(chunk_source_blocks(doc_b), start=offset):
        chunks.append({**chunk, "chunk_id": f"CHUNK-{index:04d}"})

    selected = select_eligibility_chunks(chunks)

    assert selected
    selected_document_ids = {
        block["document_id"]
        for chunk in selected
        for block in chunk["source_blocks"]
    }
    assert selected_document_ids == {"doc-a"}


def test_validate_slot_rejects_hallucinated_raw():
    ok, reason, source = validate_extracted_slot(
        {
            "유형": "실적요건",
            "raw": "최근 5년 실적 10억원 이상",
            "기간_raw": "최근 5년",
            "금액_raw": "10억원 이상",
            "근거조항": "3.1",
        },
        _chunks(),
    )

    assert ok is False
    assert "본문에 존재하지 않음" in reason
    assert source is None


def test_validate_slot_rejects_wrong_clause_reference():
    ok, reason, source = validate_extracted_slot(
        {
            "유형": "실적요건",
            "raw": "최근 3년 실적 5억원 이상",
            "기간_raw": "최근 3년",
            "금액_raw": "5억원 이상",
            "근거조항": "9.9",
        },
        _chunks(),
    )

    assert ok is False
    assert "실제 조항 라벨과 불일치" in reason
    assert source is not None


def test_extract_legacy_slots_keeps_source_provenance():
    def fake_extract(system, body, schema):
        assert "입찰 참가자격" in body
        assert "제출서류" not in body
        assert "문서 doc-1" in body
        assert schema["name"] == "eligibility_slots"
        return {
            "requirements": [
                {
                    "유형": "실적요건",
                    "raw": "최근 3년 실적 5억원 이상",
                    "기간_raw": "최근 3년",
                    "금액_raw": "5억원 이상",
                    "근거조항": "3.1",
                }
            ]
        }

    result = extract_legacy_slots(_chunks(), structured_extract=fake_extract)

    assert result["status"] == "ok"
    assert len(result["slots"]) == 1
    slot = result["slots"][0]
    assert slot["_source_chunk_id"] == "CHUNK-0001"
    assert slot["_source_blocks"][0]["page"] == 3
    assert slot["_source_blocks"][0]["document_id"] == "doc-1"


def test_extract_legacy_slots_retries_when_all_slots_fail_validation():
    calls = {"count": 0}

    def fake_extract(system, body, schema):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "requirements": [
                    {
                        "유형": "실적요건",
                        "raw": "존재하지 않는 문장",
                        "기간_raw": None,
                        "금액_raw": None,
                        "근거조항": "3.1",
                    }
                ]
            }
        return {"requirements": []}

    result = extract_legacy_slots(_chunks(), structured_extract=fake_extract, max_retry=1)

    assert calls["count"] == 2
    assert result["status"] == "ok"
    assert result["slots"] == []
