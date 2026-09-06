from apps.api.app.ai.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)


def _input():
    return QualificationAnalysisInput(
        notice_id="notice-1",
        notice_version_id="version-2",
        documents=[
            QualificationDocumentInput(
                document_id="doc-1",
                extracted_text_sha256="sha-1",
                extracted_blocks=[
                    {
                        "block_index": 0,
                        "page": 3,
                        "location": "p.3",
                        "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 2건 이상, 합계 4억원 이상",
                    }
                ],
            )
        ],
    )


def test_pipeline_returns_canonical_requirement_and_evidence():
    def fake_extract(system, body, schema):
        return {
            "requirements": [
                {
                    "유형": "실적요건",
                    "raw": "최근 3년 실적 2건 이상, 합계 4억원 이상",
                    "기간_raw": "최근 3년",
                    "금액_raw": "4억원 이상",
                    "근거조항": "3.1",
                }
            ]
        }

    def fake_normalize(raw):
        if "4억원" in raw:
            return {
                "raw": raw,
                "value": 400000000,
                "unit": "KRW",
                "op": ">=",
                "parse_status": "success",
            }
        if "3년" in raw:
            return {
                "raw": raw,
                "value": 36,
                "unit": "MONTH",
                "op": None,
                "parse_status": "success",
            }
        raise AssertionError(raw)

    result = analyze_qualification_documents(
        _input(),
        structured_extract=fake_extract,
        normalize_value=fake_normalize,
    )

    assert result.status == "SUCCEEDED"
    assert result.notice_id == "notice-1"
    assert result.notice_version_id == "version-2"
    assert result.document_ids == ["doc-1"]
    assert {item.type for item in result.requirements} == {
        "PERFORMANCE_AMOUNT",
        "PERFORMANCE_COUNT",
    }
    assert result.evidence[0].document_id == "doc-1"
    assert result.evidence[0].location.page == 3
    assert result.evidence[0].quote == "최근 3년 실적 2건 이상, 합계 4억원 이상"
    assert all(item.evidence_keys == [result.evidence[0].evidence_key] for item in result.requirements)


def test_pipeline_keeps_documents_separate_and_chunk_ids_unique():
    analysis_input = QualificationAnalysisInput(
        notice_id="notice-1",
        notice_version_id="version-1",
        documents=[
            QualificationDocumentInput(
                document_id="doc-a",
                extracted_blocks=[
                    {
                        "block_index": 0,
                        "page": 1,
                        "location": "p.1",
                        "text": "1. 개요",
                    }
                ],
            ),
            QualificationDocumentInput(
                document_id="doc-b",
                extracted_blocks=[
                    {
                        "block_index": 0,
                        "page": 2,
                        "location": "p.2",
                        "text": "2. 입찰 참가자격\n2.1 서울 소재 업체",
                    }
                ],
            ),
        ],
    )

    captured = {}

    def fake_extract(system, body, schema):
        captured["body"] = body
        return {
            "requirements": [
                {
                    "유형": "지역요건",
                    "raw": "서울 소재 업체",
                    "기간_raw": None,
                    "금액_raw": None,
                    "근거조항": "2.1",
                }
            ]
        }

    result = analyze_qualification_documents(
        analysis_input,
        structured_extract=fake_extract,
    )

    assert result.status == "SUCCEEDED"
    assert result.document_ids == ["doc-a", "doc-b"]
    assert result.evidence[0].document_id == "doc-b"
    assert len(set(result.target_chunk_ids)) == len(result.target_chunk_ids)
    assert "서울 소재 업체" in captured["body"]


def test_pipeline_fails_cleanly_when_no_usable_blocks():
    result = analyze_qualification_documents(
        QualificationAnalysisInput(
            notice_id="notice-1",
            notice_version_id="version-1",
            documents=[
                QualificationDocumentInput(
                    document_id="doc-empty",
                    extracted_blocks=[{"block_index": 0, "text": "   "}],
                )
            ],
        ),
        structured_extract=lambda system, body, schema: {"requirements": []},
    )

    assert result.status == "FAILED"
    assert result.requirements == []
    assert result.evidence == []
    assert result.diagnostics[0].code == "EXTRACTION_FAILED"


def test_pipeline_rejects_duplicate_backend_document_ids():
    try:
        QualificationAnalysisInput(
            notice_id="notice-1",
            notice_version_id="version-1",
            documents=[
                QualificationDocumentInput(document_id="dup"),
                QualificationDocumentInput(document_id="dup"),
            ],
        )
    except ValueError as error:
        assert "document_id values must be unique" in str(error)
    else:
        raise AssertionError("duplicate document ids should be rejected")
