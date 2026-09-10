from apps.api.app.ai.extraction.backend_blocks import canonical_source_blocks
from apps.api.app.ai.chunking import chunk_source_blocks
from apps.api.app.ai.extraction.requirement_extraction import (
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


def test_an_unverifiable_clause_reference_is_dropped_not_fatal():
    """근거조항이 어긋나도 원문 대조를 통과한 요건은 살린다.

    근거조항은 EvidenceLocation.clause_label 로만 가는 표시용 값이고 판정에는
    쓰이지 않는다. 환각을 막는 장치는 raw / *_raw 원문 대조이며, 그건 이미 통과한
    상태다. 참조 하나 때문에 근거가 확실한 요건을 버리면 잃는 쪽이 훨씬 크다.
    """
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
    assert source is not None
    # 확인되지 않은 참조는 남기지 않는다 — 틀린 위치를 화면에 띄우는 것보다 낫다.
    assert slot["근거조항"] is None
    assert slot["_reference_kind"] == "UNVERIFIED"


def test_a_statute_citation_is_kept_but_not_used_as_a_document_label():
    """공고문은 자격요건을 거의 전부 법령 인용으로 쓴다.

    모델이 그 법령 조문을 근거조항에 넣는 건 자연스러운 일이고, 그걸 문서 조항
    번호로 오인해 요건을 버리면 안 된다. 다만 화면에 문서 위치인 것처럼 보여서도
    안 되므로 clause_label 에서는 떼어내고 별도로 보존한다.
    """
    chunks = [
        {
            "chunk_id": "CHUNK-0001",
            "clause_label": "2",
            "text": (
                "2. 입찰 참가자격\n"
                "「국가계약법 시행령 제12조(경쟁입찰의 참가자격) 및 동법 시행규칙 "
                "제14조(입찰참가 자격요건의 증명)의 자격요건을 갖춘 자"
            ),
            "source_blocks": [],
        }
    ]
    slot = {
        "유형": "기타요건",
        "raw": "「국가계약법 시행령 제12조(경쟁입찰의 참가자격) 및 동법 시행규칙 제14조(입찰참가 자격요건의 증명)의 자격요건을 갖춘 자",
        "근거조항": "제12조, 제14조",
    }
    ok, reason, source = validate_extracted_slot(slot, chunks)

    assert ok is True
    assert slot["_reference_kind"] == "STATUTE"
    assert slot["_statute_reference"] == "제12조, 제14조"
    assert slot["근거조항"] is None


def test_a_real_document_label_is_kept():
    slot = {
        "유형": "실적요건",
        "raw": "최근 3년 실적 5억원 이상",
        "기간_raw": "최근 3년",
        "금액_raw": "5억원 이상",
        "근거조항": "3.1",
    }
    ok, _reason, _source = validate_extracted_slot(slot, _chunks())

    assert ok is True
    assert slot["_reference_kind"] == "DOCUMENT_CLAUSE"
    assert slot["근거조항"] == "3.1"


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
    assert result["dropped_requirements"] == [
        {
            "raw": "존재하지 않는 문장",
            "reason_code": "RAW_NOT_FOUND_IN_SOURCE",
        }
    ]


def test_rejected_requirement_keeps_full_raw_and_stable_reason_code():
    rejected_raw = "원문에 존재하지 않는 매우 긴 탈락 요건 " + "가" * 80

    def fake_extract(_system, _body, _schema):
        return {
            "requirements": [
                {"유형": "지역요건", "raw": "서울 소재 업체", "지역_raw": "서울"},
                {"유형": "지역요건", "raw": rejected_raw, "지역_raw": "부산"},
            ]
        }

    result = extract_legacy_slots(_chunks(), structured_extract=fake_extract)

    assert result["dropped_requirements"] == [
        {"raw": rejected_raw, "reason_code": "RAW_NOT_FOUND_IN_SOURCE"}
    ]
    assert rejected_raw not in result["notes"]


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
    """근거조항은 근거 문장이 실제로 있던 청크의 라벨이어야 한다.

    처리 방식이 바뀌었다. 예전에는 라벨이 어긋나면 슬롯 전체를 버렸는데, 그러면
    잘못된 위치 하나 때문에 멀쩡한 요건까지 사라진다. 지금은 요건은 남기고
    **위치 라벨만 지운다** — raw 자체는 이미 원문 대조를 통과한 상태다.

    위치를 못 쓰게 만든다는 안전 성질은 그대로다. 화면이 엉뚱한 조항을 가리키는
    일은 여전히 막는다.
    """
    from apps.api.app.ai.extraction.requirement_extraction import validate_extracted_slot

    chunks = [
        {"text": "안내문\n" * 40 + "2-1-1. 서울 소재 업체", "clause_label": "2"},
        {"text": "9. 다른 문서", "clause_label": "9"},
    ]

    # 근거 청크(라벨 2) 본문에 줄 머리로 있는 번호는 그 청크의 라벨로 인정한다.
    grounded = {"raw": "서울 소재 업체", "근거조항": "2-1-1"}
    assert validate_extracted_slot(grounded, chunks)[0]
    assert grounded["근거조항"] == "2-1-1"

    # "9" 는 다른 청크의 라벨이다. 요건은 살리되 위치는 못 쓰게 비운다.
    misattributed = {"raw": "서울 소재 업체", "근거조항": "9"}
    assert validate_extracted_slot(misattributed, chunks)[0]
    assert misattributed["근거조항"] is None
    assert misattributed["_reference_kind"] == "UNVERIFIED"
