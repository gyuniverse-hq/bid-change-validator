from apps.api.app.ai.backend_blocks import canonical_source_blocks
from apps.api.app.ai.chunking import chunk_source_blocks
from apps.api.app.ai.legacy_slots import adapt_legacy_slot


def test_pdf_backend_block_contract_is_preserved() -> None:
    blocks = canonical_source_blocks(
        document_id="pdf-doc",
        text_sha256="pdf-sha",
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
            "source_sha256": "pdf-sha",
        }
    ]


def test_hwpx_backend_block_contract_is_preserved() -> None:
    blocks = canonical_source_blocks(
        document_id="hwpx-doc",
        text_sha256="hwpx-sha",
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
    assert blocks[0]["source_sha256"] == "hwpx-sha"


def test_merged_semantic_chunk_keeps_every_source_block_in_order() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-1",
        text_sha256="sha",
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


def test_backend_block_location_survives_semantic_chunking() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-1",
        text_sha256="abc123",
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
