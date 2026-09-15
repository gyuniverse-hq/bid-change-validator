from apps.api.app.ai.qualification.extraction.backend_blocks import canonical_source_blocks
from apps.api.app.ai.qualification.extraction.chunking import chunk_source_blocks
from apps.api.app.ai.qualification.extraction.requirement_extraction import SLOT_SCHEMA, extract_legacy_slots, select_eligibility_chunks, validate_extracted_slot


def _chunks():
    blocks = canonical_source_blocks(document_id="doc-1", text_sha256="sha", blocks=[
        {"block_index": 0, "page": 3, "location": "p.3", "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 5억원 이상\n3.2 서울 소재 업체\n3.3 중소기업자만 참가 가능"},
        {"block_index": 1, "page": 4, "location": "p.4", "text": "4. 제출서류\n실적증명서 제출"}])
    return chunk_source_blocks(blocks)


def test_slot_schema_exposes_all_canonical_extraction_paths():
    item = SLOT_SCHEMA["schema"]["properties"]["requirements"]["items"]
    assert set(item["properties"]["유형"]["enum"]) == {"실적요건", "인력요건", "인증요건", "면허요건", "등록요건", "지역요건", "업종요건", "경험분야요건", "기업규모요건", "기타요건"}
    for field in ("기간_raw", "금액_raw", "건수_raw", "업종_raw", "경험분야_raw", "지역_raw", "인원_raw", "인력역할_raw", "등록인증_raw", "발급기관_raw", "기업규모_raw", "실적기관_raw"):
        assert field in item["properties"]
    assert set(item["required"]) == set(item["properties"])


def test_select_eligibility_section_includes_children_until_next_top_level():
    assert [c["clause_label"] for c in select_eligibility_chunks(_chunks())] == ["3", "3.1", "3.2", "3.3"]


def test_select_eligibility_section_does_not_cross_backend_document_boundary():
    a = canonical_source_blocks(document_id="doc-a", text_sha256="sha-a", blocks=[{"block_index": 0, "page": 1, "location": "p.1", "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 5억원 이상"}])
    b = canonical_source_blocks(document_id="doc-b", text_sha256="sha-b", blocks=[{"block_index": 0, "page": 1, "location": "p.1", "text": "이 문장은 다른 문서의 서두이며 자격요건이 아니다."}])
    chunks = chunk_source_blocks(a)
    chunks.extend({**c, "chunk_id": f"CHUNK-{i:04d}"} for i, c in enumerate(chunk_source_blocks(b), start=len(chunks)))
    assert {b["document_id"] for c in select_eligibility_chunks(chunks) for b in c["source_blocks"]} == {"doc-a"}


def test_validate_slot_rejects_hallucinated_raw():
    ok, reason, source = validate_extracted_slot({"유형": "실적요건", "raw": "최근 5년 실적 10억원 이상", "기간_raw": "최근 5년", "금액_raw": "10억원 이상", "근거조항": "3.1"}, _chunks())
    assert ok is False and "본문에 존재하지 않음" in reason and source is None


def test_validate_slot_rejects_hallucinated_detail_field():
    ok, reason, source = validate_extracted_slot({"유형": "실적요건", "raw": "최근 3년 실적 5억원 이상", "기간_raw": "최근 3년", "금액_raw": "5억원 이상", "경험분야_raw": "공공기관 정보시스템 구축", "근거조항": "3.1"}, _chunks())
    assert ok is False and "경험분야_raw가 본문에 존재하지 않음" in reason and source is not None


def test_validate_slot_rejects_hallucinated_company_size_detail():
    ok, reason, source = validate_extracted_slot({"유형": "기업규모요건", "raw": "중소기업자만 참가 가능", "기업규모_raw": "대기업", "근거조항": "3.3"}, _chunks())
    assert ok is False and "기업규모_raw가 본문에 존재하지 않음" in reason and source is not None


def test_validate_slot_clears_wrong_clause_reference_without_losing_requirement():
    slot = {"유형": "실적요건", "raw": "최근 3년 실적 5억원 이상", "기간_raw": "최근 3년", "금액_raw": "5억원 이상", "근거조항": "9.9"}
    ok, reason, source = validate_extracted_slot(slot, _chunks())
    assert ok is True and reason == "" and slot["근거조항"] is None and source is not None


def test_extract_legacy_slots_keeps_source_provenance():
    def model(system, body, schema):
        assert "입찰 참가자격" in body and "제출서류" not in body and "문서 doc-1" in body
        assert schema["name"] == "eligibility_slots"
        return {"requirements": [{"유형": "실적요건", "raw": "최근 3년 실적 5억원 이상", "기간_raw": "최근 3년", "금액_raw": "5억원 이상", "근거조항": "3.1"}]}
    result = extract_legacy_slots(_chunks(), structured_extract=model)
    assert result["status"] == "ok" and len(result["slots"]) == 1
    slot = result["slots"][0]
    assert slot["_source_chunk_id"] == "CHUNK-0001"
    assert slot["_source_blocks"][0]["page"] == 3 and slot["_source_blocks"][0]["document_id"] == "doc-1"


def test_extract_legacy_slots_retries_when_all_slots_fail_validation():
    calls = []
    def model(*args):
        calls.append(1)
        return {"requirements": [{"유형": "실적요건", "raw": "존재하지 않는 문장", "근거조항": "3.1"}]} if len(calls) == 1 else {"requirements": []}
    result = extract_legacy_slots(_chunks(), structured_extract=model, max_retry=1)
    assert len(calls) == 2 and result["status"] == "partial" and result["slots"] == []
    assert result["dropped_requirements"] == [{"raw": "존재하지 않는 문장", "reason_code": "RAW_NOT_FOUND_IN_SOURCE"}]


def test_quote_suffix_cannot_be_fabricated_after_matching_prefix():
    raw = "서울특별시에주된영업소를두고입찰공고일전일부터계약체결일까지계속하여해당소재지에서사업을운영하는업체는"
    assert not validate_extracted_slot({"raw": raw + " 모든 자격이 면제된다."}, [{"text": raw + " 등록하여야 한다."}])[0]
    assert validate_extracted_slot({"raw": "서울  소재\n업체"}, [{"text": "서울 소재 업체"}])[0]


def test_truncated_input_is_partial_and_not_silently_successful():
    chunks = [{"text": "서울 소재 업체\n" + "긴 원문 " * 10000, "chunk_id": "long"}]
    result = extract_legacy_slots(chunks, structured_extract=lambda *a: {"requirements": [{"유형": "지역요건", "raw": "서울 소재 업체", "지역_raw": "서울"}]})
    assert result["status"] == "partial" and "길이 제한" in result["notes"]


def test_other_document_requirements_are_not_suppressed_by_section_anchor():
    chunks = _chunks() + [{"text": "개발 인력 5명 이상 보유", "chunk_id": "extra", "source_blocks": [{"document_id": "rfp"}]}]
    assert chunks[-1] in select_eligibility_chunks(chunks)


def test_clause_reference_must_belong_to_the_grounded_chunk():
    chunks = [{"text": "안내문\n" * 40 + "2-1-1. 서울 소재 업체", "clause_label": "2"}, {"text": "9. 다른 문서", "clause_label": "9"}]
    assert validate_extracted_slot({"raw": "서울 소재 업체", "근거조항": "2-1-1"}, chunks)[0]
    slot = {"raw": "서울 소재 업체", "근거조항": "9"}
    assert validate_extracted_slot(slot, chunks)[0] and slot["근거조항"] is None


def test_statute_citation_is_preserved_in_raw_not_document_location():
    raw = "국가계약법 시행령 제12조 및 시행규칙 제14조의 자격요건을 갖춘 자"
    slot = {"유형": "기타요건", "raw": raw, "근거조항": "제12조, 제14조"}
    assert validate_extracted_slot(slot, [{"text": raw, "clause_label": "2"}])[0]
    assert slot["raw"] == raw and slot["근거조항"] is None


def test_valid_document_label_is_retained():
    slot = {"raw": "최근 3년 실적 5억원 이상", "근거조항": "3.1"}
    assert validate_extracted_slot(slot, _chunks())[0] and slot["근거조항"] == "3.1"


def test_successful_retry_is_not_penalized_by_previous_rejection():
    answers = iter([{"requirements": [{"raw": "원문에 없는 요건"}]}, {"requirements": [{"raw": "서울 소재 업체", "유형": "지역요건", "지역_raw": "서울"}]}])
    result = extract_legacy_slots(_chunks(), structured_extract=lambda *args: next(answers))
    assert result["status"] == "ok" and len(result["slots"]) == 1 and result["notes"] == ""


def test_section_body_under_korean_sub_labels_is_kept_as_children():
    texts = ["3. 입찰참가자격", "가. 나라장터 입찰참가등록을 마친 자", "나. 식품위생법에 의거 단체급식업 등록업체(업종코드 1450)",
             "1) 등록증 사본 제출", "다. 충청북도에 주된 영업소가 있는 업체", "4. 입찰방법", "가. 전자입찰"]
    blocks = canonical_source_blocks(document_id="doc-k", text_sha256="sha-k", blocks=[{"block_index": i, "page": 1, "location": "p.1", "text": t} for i, t in enumerate(texts)])
    selected = "\n".join(c["text"] for c in select_eligibility_chunks(chunk_source_blocks(blocks)))
    assert "1450" in selected and "충청북도" in selected and "등록증 사본" in selected and "전자입찰" not in selected


def test_dotted_eligibility_heading_keeps_korean_children():
    texts = ["3.1 입찰참가자격", "가. 업종코드 1253 등록업체", "나. 충청북도 소재 업체", "3.2 입찰방법", "가. 전자입찰"]
    blocks = canonical_source_blocks(document_id="doc-dotted", text_sha256="sha-dotted", blocks=[{"block_index": i, "text": t} for i, t in enumerate(texts)])
    selected = "\n".join(c["text"] for c in select_eligibility_chunks(chunk_source_blocks(blocks)))
    assert "1253" in selected and "충청북도" in selected and "전자입찰" not in selected


def test_parenthesized_number_can_be_an_eligibility_anchor():
    texts = ["1) 입찰참가자격", "가) 업종코드 1169 등록업체", "나) 서울특별시 소재 업체", "2) 제출서류", "가) 법인등기부등본"]
    blocks = canonical_source_blocks(document_id="doc-paren", text_sha256="sha-paren", blocks=[{"block_index": i, "text": t} for i, t in enumerate(texts)])
    selected = "\n".join(c["text"] for c in select_eligibility_chunks(chunk_source_blocks(blocks)))
    assert "1169" in selected and "서울특별시" in selected and "법인등기부등본" not in selected


def test_grounding_restores_compatibility_dots_to_actual_source():
    raw = "건설폐기물수집·운반업 (업종코드 : 6728)을 등록한 업체"
    source = "건설폐기물수집․운반업 (업종코드 : 6728)을 등록한 업체"
    slot = {"유형": "업종요건", "raw": raw, "업종_raw": "건설폐기물수집·운반업"}
    ok, reason, source_chunk = validate_extracted_slot(slot, [{"text": source}])
    assert ok is True and reason == "" and source_chunk is not None
    assert slot["raw"] == source and slot["업종_raw"] == "건설폐기물수집․운반업"
