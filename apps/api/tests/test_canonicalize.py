from apps.api.app.ai.extraction.canonicalize import canonicalize_validated_slot


def test_validated_slot_becomes_atomic_requirements_with_shared_evidence() -> None:
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
        "근거조항": "3.1",
        "_source_chunk_id": "CHUNK-0001",
        "_source_blocks": [
            {
                "document_id": "doc-1",
                "block_index": 4,
                "page": 14,
                "section_index": None,
                "paragraph_index": None,
                "location": "p.14",
                "source_line_start": 3,
                "source_line_end": 4,
                "source_sha256": "sha-1",
                "extracted_text_sha256": "text-sha-1",
                "text": "3.1 최근 3년 실적 2건 이상, 합계 4억원 이상",
            }
        ],
    }

    requirements, evidence, diagnostics = canonicalize_validated_slot(
        slot,
        notice_version_id="version-2",
        key_prefix="REQ-001",
    )

    assert diagnostics == []
    assert {requirement.type for requirement in requirements} == {
        "PERFORMANCE_AMOUNT",
        "PERFORMANCE_COUNT",
    }
    assert len(evidence) == 1
    assert evidence[0].evidence_key == "REQ-001-EVD"
    assert evidence[0].document_id == "doc-1"
    assert evidence[0].chunk_id == "CHUNK-0001"
    assert evidence[0].location.page == 14
    assert evidence[0].location.block_start == 4
    assert evidence[0].location.source_line_start == 3
    assert evidence[0].quote == slot["raw"]
    assert evidence[0].source_sha256 == "sha-1"
    assert evidence[0].extracted_text_sha256 == "text-sha-1"
    assert all(requirement.evidence_keys == ["REQ-001-EVD"] for requirement in requirements)


def test_hwpx_evidence_keeps_section_and_paragraph_without_fake_page() -> None:
    slot = {
        "유형": "지역요건",
        "raw": "서울특별시 소재 업체",
        "지역_raw": "서울특별시",
        "근거조항": "3.2",
        "_source_chunk_id": "CHUNK-0002",
        "_source_blocks": [
            {
                "document_id": "doc-hwpx",
                "block_index": 8,
                "page": None,
                "section_index": 1,
                "paragraph_index": 7,
                "location": "section 2 · paragraph 8",
                "source_sha256": "sha-hwpx",
                "extracted_text_sha256": "text-sha-hwpx",
                "text": "3.2 서울특별시 소재 업체",
            }
        ],
    }

    requirements, evidence, diagnostics = canonicalize_validated_slot(
        slot,
        notice_version_id="version-2",
        key_prefix="REQ-002",
    )

    assert diagnostics == []
    assert [requirement.type for requirement in requirements] == ["REGION"]
    assert requirements[0].value == "서울특별시"
    assert evidence[0].location.page is None
    assert evidence[0].location.section_index == 1
    assert evidence[0].location.paragraph_start == 7
    assert evidence[0].location.paragraph_end == 7
    assert evidence[0].location.display == "section 2 · paragraph 8"
    assert evidence[0].extracted_text_sha256 == "text-sha-hwpx"


def test_an_unmapped_slot_is_recorded_with_its_evidence() -> None:
    requirements, evidence, diagnostics = canonicalize_validated_slot(
        {
            "유형": "기타요건",
            "raw": "자동 판정 범위 밖 조건",
            "_source_chunk_id": "CHUNK-0003",
            "_source_blocks": [
                {
                    "document_id": "doc-1",
                    "block_index": 9,
                    "page": 15,
                    "location": "p.15",
                    "source_sha256": "sha-1",
                    "text": "자동 판정 범위 밖 조건",
                }
            ],
        },
        notice_version_id="version-2",
        key_prefix="REQ-003",
    )

    # 판정은 하지 않지만 기록은 남는다. 근거를 같이 버리면 사용자 입장에서
    # "확인했는데 판정 대상이 아님" 과 "아예 못 봤음" 이 구분되지 않는다.
    assert requirements == []
    assert len(evidence) == 1
    assert evidence[0].document_id == "doc-1"
    assert evidence[0].location.page == 15
    assert evidence[0].quote == "자동 판정 범위 밖 조건"

    # 진단이 그 근거를 참조하므로 떠 있는 근거가 아니다.
    assert diagnostics[0]["code"] == "UNMAPPED_REQUIREMENT"
    assert diagnostics[0]["evidence_keys"] == [evidence[0].evidence_key]


def test_a_registration_requirement_with_an_industry_code_maps_to_industry() -> None:
    """The code is the checkable form of the condition, so it wins over the name.

    Taken from a real notice: matching "소프트웨어사업(컴퓨터관련서비스사업)" against a
    company's certification list fails on wording alone, while 1468 either is or
    is not among its registered industries.
    """
    from apps.api.app.ai.extraction.legacy_slots import adapt_legacy_slot

    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "등록요건",
            "raw": "나라장터(G2B)에 입찰참가자격을 등록한 자\n"
            "- 소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)",
            "등록인증_raw": "소프트웨어사업(컴퓨터관련서비스사업)",
        },
        notice_version_id="nv-1",
        key_prefix="REQ-0001",
    )

    assert [item.type for item in requirements] == ["INDUSTRY"]
    assert requirements[0].value == "1468"
    assert requirements[0].scope["kind"] == "REGISTRATION"
    assert requirements[0].scope["industry_name"] == "소프트웨어사업(컴퓨터관련서비스사업)"
    # One condition, one requirement: emitting the name as well would judge it
    # twice and let the fuzzier matcher decide.
    assert diagnostics == []


def test_a_certification_without_a_code_still_maps_to_registration() -> None:
    from apps.api.app.ai.extraction.legacy_slots import adapt_legacy_slot

    requirements, _ = adapt_legacy_slot(
        {
            "유형": "인증요건",
            "raw": "ISO/IEC 27001 정보보호 관리체계 인증을 보유한 업체",
            "등록인증_raw": "ISO/IEC 27001",
        },
        notice_version_id="nv-1",
        key_prefix="REQ-0002",
    )

    assert [item.type for item in requirements] == ["REGISTRATION_CERTIFICATION"]
    assert requirements[0].value == "ISO/IEC 27001"


def test_the_industry_code_is_reached_from_either_slot_classification() -> None:
    """The extractor labels this same sentence 업종요건 or 등록요건 from run to run.

    If only one branch found the code, the verdict would change with the label
    rather than with the notice, which is the sort of instability that makes a
    judgment untrustworthy.
    """
    from apps.api.app.ai.extraction.legacy_slots import adapt_legacy_slot

    raw = (
        "나라장터(G2B)에 다음 분야의 입찰참가자격을 등록한 자\n"
        "- 소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)"
    )
    for slot_type in ("업종요건", "등록요건"):
        requirements, _ = adapt_legacy_slot(
            {
                "유형": slot_type,
                "raw": raw,
                "업종_raw": "소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)",
                "등록인증_raw": "소프트웨어사업(컴퓨터관련서비스사업)",
            },
            notice_version_id="nv-1",
            key_prefix="REQ-0001",
        )
        assert [item.type for item in requirements] == ["INDUSTRY"], slot_type
        assert requirements[0].value == "1468", slot_type
