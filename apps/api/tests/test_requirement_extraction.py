from apps.api.app.ai.backend_blocks import canonical_source_blocks
from apps.api.app.ai.chunking import chunk_source_blocks
from apps.api.app.ai.requirement_extraction import (
    SLOT_SCHEMA,
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
                "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 5억원 이상\n3.2 서울 소재 업체\n3.3 중소기업자만 참가 가능",
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


def test_slot_schema_exposes_all_canonical_extraction_paths():
    item_schema = SLOT_SCHEMA["schema"]["properties"]["requirements"]["items"]
    slot_types = set(item_schema["properties"]["유형"]["enum"])

    assert {
        "실적요건",
        "인력요건",
        "인증요건",
        "면허요건",
        "등록요건",
        "지역요건",
        "업종요건",
        "경험분야요건",
        "기업규모요건",
        "기타요건",
    } == slot_types
    for field_name in (
        "기간_raw",
        "금액_raw",
        "건수_raw",
        "업종_raw",
        "경험분야_raw",
        "지역_raw",
        "인원_raw",
        "인력역할_raw",
        "등록인증_raw",
        "발급기관_raw",
        "기업규모_raw",
        "실적기관_raw",
    ):
        assert field_name in item_schema["properties"]
    assert set(item_schema["required"]) == set(item_schema["properties"])


def test_select_eligibility_section_includes_children_until_next_top_level():
    selected = select_eligibility_chunks(_chunks())
    assert [chunk["clause_label"] for chunk in selected] == ["3", "3.1", "3.2", "3.3"]


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


def test_validate_slot_rejects_hallucinated_detail_field():
    ok, reason, source = validate_extracted_slot(
        {
            "유형": "실적요건",
            "raw": "최근 3년 실적 5억원 이상",
            "기간_raw": "최근 3년",
            "금액_raw": "5억원 이상",
            "경험분야_raw": "공공기관 정보시스템 구축",
            "근거조항": "3.1",
        },
        _chunks(),
    )

    assert ok is False
    assert "경험분야_raw가 본문에 존재하지 않음" in reason
    assert source is not None


def test_validate_slot_rejects_hallucinated_company_size_detail():
    ok, reason, source = validate_extracted_slot(
        {
            "유형": "기업규모요건",
            "raw": "중소기업자만 참가 가능",
            "기업규모_raw": "대기업",
            "근거조항": "3.3",
        },
        _chunks(),
    )

    assert ok is False
    assert "기업규모_raw가 본문에 존재하지 않음" in reason
    assert source is not None


def test_validate_slot_clears_wrong_clause_reference_without_losing_requirement():
    slot = {
        "유형": "실적요건",
        "raw": "최근 3년 실적 5억원 이상",
        "기간_raw": "최근 3년",
        "금액_raw": "5억원 이상",
        "근거조항": "9.9",
    }
    ok, reason, source = validate_extracted_slot(slot, _chunks())

    assert ok is True
    assert reason == ""
    assert slot["근거조항"] is None
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
                        "근거조항": "3.1",
                    }
                ]
            }
        return {"requirements": []}

    result = extract_legacy_slots(_chunks(), structured_extract=fake_extract, max_retry=1)

    assert calls["count"] == 2
    assert result["status"] == "partial"
    assert result["slots"] == []
    assert "존재하지 않는 문장" in result["notes"]


def test_quote_suffix_cannot_be_fabricated_after_matching_prefix():
    raw = "서울특별시에주된영업소를두고입찰공고일전일부터계약체결일까지계속하여해당소재지에서사업을운영하는업체는"
    assert not validate_extracted_slot({"raw": raw + " 모든 자격이 면제된다."}, [{"text": raw + " 등록하여야 한다."}])[0]
    assert validate_extracted_slot({"raw": "서울  소재\n업체"}, [{"text": "서울 소재 업체"}])[0]


def test_truncated_input_is_partial_and_not_silently_successful():
    chunks = [{"text": "서울 소재 업체\n" + "긴 원문 " * 10000, "chunk_id": "long"}]
    result = extract_legacy_slots(chunks, structured_extract=lambda *args: {"requirements": [{"유형": "지역요건", "raw": "서울 소재 업체", "지역_raw": "서울"}]})
    assert result["status"] == "partial"
    assert "길이 제한" in result["notes"]


def test_other_document_requirements_are_not_suppressed_by_section_anchor():
    chunks = _chunks() + [{"text": "개발 인력 5명 이상 보유", "chunk_id": "extra", "source_blocks": [{"document_id": "rfp"}]}]
    assert chunks[-1] in select_eligibility_chunks(chunks)


def test_clause_reference_must_belong_to_the_grounded_chunk():
    from apps.api.app.ai.requirement_extraction import validate_extracted_slot
    chunks = [{"text": "안내문\n" * 40 + "2-1-1. 서울 소재 업체", "clause_label": "2"}, {"text": "9. 다른 문서", "clause_label": "9"}]
    assert validate_extracted_slot({"raw": "서울 소재 업체", "근거조항": "2-1-1"}, chunks)[0]
    slot = {"raw": "서울 소재 업체", "근거조항": "9"}
    assert validate_extracted_slot(slot, chunks)[0]
    assert slot["근거조항"] is None


def test_statute_citation_is_preserved_in_raw_not_document_location():
    raw = "국가계약법 시행령 제12조 및 시행규칙 제14조의 자격요건을 갖춘 자"
    slot = {"유형": "기타요건", "raw": raw, "근거조항": "제12조, 제14조"}
    assert validate_extracted_slot(slot, [{"text": raw, "clause_label": "2"}])[0]
    assert slot["raw"] == raw
    assert slot["근거조항"] is None


def test_valid_document_label_is_retained():
    slot = {"raw": "최근 3년 실적 5억원 이상", "근거조항": "3.1"}
    assert validate_extracted_slot(slot, _chunks())[0]
    assert slot["근거조항"] == "3.1"


def test_successful_retry_is_not_penalized_by_previous_rejection():
    answers = iter([
        {"requirements": [{"raw": "원문에 없는 요건"}]},
        {"requirements": [{"raw": "서울 소재 업체", "유형": "지역요건", "지역_raw": "서울"}]},
    ])
    result = extract_legacy_slots(_chunks(), structured_extract=lambda *args: next(answers))
    assert result["status"] == "ok"
    assert len(result["slots"]) == 1
    assert result["notes"] == ""
