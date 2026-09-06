from apps.api.app.ai.backend_blocks import canonical_source_blocks
from apps.api.app.ai.chunking import chunk_source_blocks
from apps.api.app.ai.legacy_slots import adapt_legacy_slot


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
