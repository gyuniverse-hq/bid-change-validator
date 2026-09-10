import pytest
from pydantic import ValidationError

from apps.api.app.ai.extraction.analysis_result import (
    RequirementAnalysisResult,
    build_requirement_analysis_result,
)
from apps.api.app.ai.contracts import Evidence, EvidenceLocation, QualificationRequirement


def _requirement(evidence_keys=None):
    return QualificationRequirement(
        requirement_key="REQ-001-AMOUNT",
        requirement_group_key="REQ-001-GROUP",
        group_operator="ALL_OF",
        notice_version_id="version-1",
        type="PERFORMANCE_AMOUNT",
        operator=">=",
        value=400000000,
        unit="KRW",
        raw="최근 3년 실적 합계 4억원 이상",
        evidence_keys=list(evidence_keys or ["REQ-001-EVD"]),
    )


def _evidence(document_id="doc-1", notice_version_id="version-1"):
    return Evidence(
        evidence_key="REQ-001-EVD",
        source_type="NOTICE_DOCUMENT",
        document_id=document_id,
        notice_version_id=notice_version_id,
        chunk_id="CHUNK-0001",
        location=EvidenceLocation(page=14, clause_label="3.1", display="p.14"),
        quote="최근 3년 실적 합계 4억원 이상",
        source_sha256="sha",
        extracted_text_sha256="text-sha",
    )


def test_build_successful_analysis_result():
    result = build_requirement_analysis_result(
        notice_id="notice-1",
        notice_version_id="version-1",
        document_ids=["doc-1"],
        target_chunk_ids=["CHUNK-0000", "CHUNK-0001"],
        canonicalized={
            "requirements": [_requirement()],
            "evidence": [_evidence()],
            "diagnostics": [],
        },
    )

    assert result.contract_version == "ai-analysis-v0.2"
    assert result.analysis_kind == "QUALIFICATION_REQUIREMENTS"
    assert result.status == "SUCCEEDED"
    assert result.notice_id == "notice-1"
    assert result.requirements[0].evidence_keys == ["REQ-001-EVD"]
    assert result.evidence[0].document_id == "doc-1"
    assert result.evidence[0].extracted_text_sha256 == "text-sha"


def test_a_structuring_failure_makes_the_result_partial():
    """유형은 알아봤는데 값을 구조화하지 못한 것 — 실제로 요건을 잃은 경우다."""
    result = build_requirement_analysis_result(
        notice_id="notice-1",
        notice_version_id="version-1",
        document_ids=["doc-1"],
        canonicalized={
            "requirements": [_requirement()],
            "evidence": [_evidence()],
            "diagnostics": [{"code": "UNMAPPED_STAFF", "raw": "인력 조건"}],
        },
    )

    assert result.status == "PARTIAL"
    assert result.diagnostics[0].kind == "PIPELINE"
    assert result.diagnostics[0].severity == "WARNING"
    assert result.requirements


def test_a_notice_fact_does_not_make_the_result_partial():
    """공고에 그렇게 적혀 있어서 판정 대상이 아닌 것은 정상 결과다.

    법령 상용구("부정당업체로 지정되지 않은 자") 한 줄 때문에 모든 공고가 PARTIAL 이
    되면 이 값으로 실제 문제를 가려낼 수 없다.
    """
    result = build_requirement_analysis_result(
        notice_id="notice-1",
        notice_version_id="version-1",
        document_ids=["doc-1"],
        canonicalized={
            "requirements": [_requirement()],
            "evidence": [_evidence()],
            "diagnostics": [
                {
                    "code": "UNMAPPED_REQUIREMENT",
                    "raw": "부정당업체로 지정되지 않은 자",
                    "evidence_keys": ["EV-1"],
                }
            ],
        },
    )

    assert result.status == "SUCCEEDED"
    diagnostic = result.diagnostics[0]
    assert diagnostic.kind == "NOTICE_FACT"
    assert diagnostic.severity == "INFO"
    # 근거를 달고 다녀야 사용자가 원문을 확인할 수 있다.
    assert diagnostic.evidence_keys == ["EV-1"]
    assert "판정하지 않고" in diagnostic.message


def test_extraction_failure_without_results_is_failed_and_empty():
    result = build_requirement_analysis_result(
        notice_id="notice-1",
        notice_version_id="version-1",
        document_ids=["doc-1"],
        extraction_status="failed",
        extraction_notes="model unavailable",
        canonicalized={"requirements": [], "evidence": [], "diagnostics": []},
    )

    assert result.status == "FAILED"
    assert result.requirements == []
    assert result.evidence == []
    assert result.diagnostics[0].code == "EXTRACTION_FAILED"


def test_result_rejects_unresolved_evidence_reference():
    with pytest.raises(ValidationError):
        RequirementAnalysisResult(
            status="SUCCEEDED",
            notice_id="notice-1",
            notice_version_id="version-1",
            document_ids=["doc-1"],
            requirements=[_requirement(["missing-evidence"])],
            evidence=[_evidence()],
        )


def test_result_rejects_evidence_from_outside_document_scope():
    with pytest.raises(ValidationError):
        RequirementAnalysisResult(
            status="SUCCEEDED",
            notice_id="notice-1",
            notice_version_id="version-1",
            document_ids=["doc-1"],
            requirements=[_requirement()],
            evidence=[_evidence(document_id="doc-2")],
        )


def test_result_rejects_mixed_notice_versions():
    with pytest.raises(ValidationError):
        RequirementAnalysisResult(
            status="SUCCEEDED",
            notice_id="notice-1",
            notice_version_id="version-1",
            document_ids=["doc-1"],
            requirements=[_requirement()],
            evidence=[_evidence(notice_version_id="version-2")],
        )
