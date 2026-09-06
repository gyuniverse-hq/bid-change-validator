from apps.api.app.ai.backend_blocks import canonical_source_blocks
from apps.api.app.ai.chunking import chunk_source_blocks
from apps.api.app.ai.legacy_slots import adapt_legacy_slot


def test_pdf_backend_block_contract_is_preserved() -> None:
    blocks = canonical_source_blocks(
        document_id="pdf-doc",
        file_sha256="pdf-file-sha",
        text_sha256="pdf-text-sha",
        blocks=[
            {
                "block_index": 0,
                "page": 14,
                "location": "p.14",
                "text": "입찰 참가자격 본문",
            }
        ],
    )

    assert blocks == [
        {
            "document_id": "pdf-doc",
            "block_index": 0,
            "page": 14,
            "section_index": None,
            "paragraph_index": None,
            "location": "p.14",
            "text": "입찰 참가자격 본문",
            "source_sha256": "pdf-file-sha",
            "extracted_text_sha256": "pdf-text-sha",
        }
    ]


def test_hwpx_backend_block_contract_is_preserved() -> None:
    blocks = canonical_source_blocks(
        document_id="hwpx-doc",
        file_sha256="hwpx-file-sha",
        text_sha256="hwpx-text-sha",
        blocks=[
            {
                "block_index": 3,
                "section_index": 1,
                "paragraph_index": 7,
                "location": "section 2 · paragraph 8",
                "text": "3.2 최근 3년 실적 5억원 이상",
            }
        ],
    )

    assert blocks[0]["document_id"] == "hwpx-doc"
    assert blocks[0]["section_index"] == 1
    assert blocks[0]["paragraph_index"] == 7
    assert blocks[0]["location"] == "section 2 · paragraph 8"
    assert blocks[0]["source_sha256"] == "hwpx-file-sha"
    assert blocks[0]["extracted_text_sha256"] == "hwpx-text-sha"


def test_merged_semantic_chunk_keeps_every_source_block_in_order() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-1",
        file_sha256="file-sha",
        text_sha256="text-sha",
        blocks=[
            {
                "block_index": 0,
                "section_index": 0,
                "paragraph_index": 0,
                "location": "section 1 · paragraph 1",
                "text": "3. 참가자격",
            },
            {
                "block_index": 1,
                "section_index": 0,
                "paragraph_index": 1,
                "location": "section 1 · paragraph 2",
                "text": "최근 3년 실적 5억원 이상",
            },
            {
                "block_index": 2,
                "section_index": 0,
                "paragraph_index": 2,
                "location": "section 1 · paragraph 3",
                "text": "관련 증빙서류를 제출해야 한다.",
            },
        ],
    )

    chunks = chunk_source_blocks(blocks)

    assert len(chunks) == 1
    assert chunks[0]["clause_label"] == "3"
    assert [block["block_index"] for block in chunks[0]["source_blocks"]] == [0, 1, 2]
    assert [block["paragraph_index"] for block in chunks[0]["source_blocks"]] == [0, 1, 2]


def test_pdf_page_block_splits_multiple_headings_and_keeps_page_locator() -> None:
    blocks = canonical_source_blocks(
        document_id="pdf-doc",
        file_sha256="pdf-file-sha",
        text_sha256="pdf-text-sha",
        blocks=[
            {
                "block_index": 0,
                "page": 14,
                "location": "p.14",
                "text": (
                    "3. 참가자격\n"
                    "최근 3년 실적 5억원 이상\n"
                    "3.1 세부 실적요건\n"
                    "유사사업 실적 2건 이상\n"
                    "4. 제출서류\n"
                    "실적증명서를 제출해야 한다."
                ),
            }
        ],
    )

    chunks = chunk_source_blocks(blocks)

    assert [chunk["clause_label"] for chunk in chunks] == ["3", "3.1", "4"]
    assert all(chunk["source_blocks"][0]["page"] == 14 for chunk in chunks)
    assert all(chunk["source_blocks"][0]["document_id"] == "pdf-doc" for chunk in chunks)
    assert [chunk["source_blocks"][0]["source_line_start"] for chunk in chunks] == [1, 3, 5]
    assert [chunk["source_blocks"][0]["source_line_end"] for chunk in chunks] == [2, 4, 6]


def test_pdf_leading_text_before_first_heading_is_not_dropped() -> None:
    blocks = canonical_source_blocks(
        document_id="pdf-doc",
        file_sha256="pdf-file-sha",
        text_sha256="pdf-text-sha",
        blocks=[
            {
                "block_index": 0,
                "page": 2,
                "location": "p.2",
                "text": "계속되는 설명 문장\n2. 계약조건\n계약기간은 12개월이다.",
            }
        ],
    )

    chunks = chunk_source_blocks(blocks)

    assert chunks[0]["clause_label"] is None
    assert chunks[0]["text"] == "계속되는 설명 문장"
    assert chunks[0]["source_blocks"][0]["page"] == 2
    assert chunks[1]["clause_label"] == "2"
    assert "계약기간은 12개월이다." in chunks[1]["text"]


def test_backend_block_location_survives_semantic_chunking() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-1",
        file_sha256="abc123",
        text_sha256="text123",
        blocks=[
            {"block_index": 0, "page": 3, "location": "p.3", "text": "3. 참가자격"},
            {"block_index": 1, "page": 3, "location": "p.3", "text": "3.1 최근 3년 실적 5억원 이상"},
        ],
    )
    chunks = chunk_source_blocks(blocks)

    assert chunks
    assert chunks[0]["source_blocks"][0]["document_id"] == "doc-1"
    assert chunks[0]["source_blocks"][0]["page"] == 3
    assert chunks[0]["source_blocks"][0]["source_sha256"] == "abc123"
    assert chunks[0]["source_blocks"][0]["extracted_text_sha256"] == "text123"


def test_legacy_performance_slot_maps_to_atomic_requirements() -> None:
    slot = {
        "유형": "실적요건",
        "raw": "최근 3년 실적 2건 이상, 합계 4억원 이상",
        "기간_norm": {"parse_status": "success", "value": 36},
        "금액_norm": {
            "parse_status": "success",
            "value": 400000000,
            "unit": "KRW",
            "op": ">=",
        },
    }

    requirements, diagnostics = adapt_legacy_slot(
        slot,
        notice_version_id="version-1",
        key_prefix="REQ-001",
    )

    assert diagnostics == []
    assert {requirement.type for requirement in requirements} == {
        "PERFORMANCE_AMOUNT",
        "PERFORMANCE_COUNT",
    }
    assert all(requirement.requirement_group_key == "REQ-001-GROUP" for requirement in requirements)


def test_legacy_other_requirement_stays_diagnostic() -> None:
    requirements, diagnostics = adapt_legacy_slot(
        {"유형": "기타요건", "raw": "자동 판정 범위 밖의 복합 조건"},
        notice_version_id="version-1",
        key_prefix="REQ-002",
    )

    assert requirements == []
    assert diagnostics[0]["code"] == "UNMAPPED_REQUIREMENT"
