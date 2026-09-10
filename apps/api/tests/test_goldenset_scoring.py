from pathlib import Path

from apps.api.app.ai.goldenset.fixtures import GoldenCase, GoldenDocument
from apps.api.app.ai.goldenset.funnel import evaluate_case_funnel
from apps.api.app.ai.goldenset.scoring import score_case
from apps.api.app.ai.goldenset.spans import GoldenSpan
from apps.api.app.scripts.retrieval_report import summarize_reports


def _chunk(text: str, document_id: str, chunk_id: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "source_blocks": [{"document_id": document_id}],
    }


def test_span_labels_survive_whitespace_changes_and_reject_traps() -> None:
    case = GoldenCase(
        notice_no="N1",
        documents=(GoldenDocument("NOTICE", "unused", "NOTICE"),),
        spans=(
            GoldenSpan("P1", "NOTICE", "POSITIVE", "대기업 및 중견기업 참여 제한"),
            GoldenSpan("T1", "RFP", "TRAP", "입찰 참가자격이 제한됨"),
        ),
    )
    chunks = [
        _chunk("대기업및 중견기업  참여 제한", "NOTICE", "CHUNK-0000"),
        _chunk("누출 시 입찰 참가자격이 제한됨", "RFP", "CHUNK-0001"),
    ]

    report = score_case(case, chunks, [chunks[0]])

    assert report["chunk_health"]["span_containment"] == 1
    assert report["retrieval"]["recall"] == 1
    assert report["retrieval"]["precision"] == 1
    assert report["retrieval"]["trap_rate"] == 0


def test_funnel_marks_a_contained_but_unretrieved_span() -> None:
    case = GoldenCase(
        notice_no="N1",
        documents=(),
        spans=(GoldenSpan("P1", "NOTICE", "POSITIVE", "직접생산확인증명서"),),
    )
    chunks = [_chunk("직접 생산 확인 증명서", "NOTICE", "CHUNK-0000")]

    row = score_case(case, chunks, [])["funnel"][0]

    assert row == {
        "span_id": "P1",
        "note": "",
        "contained": True,
        "retrieved": False,
        "extracted": None,
        "canonical": None,
        "judgment": None,
    }


def test_canonical_stage_checks_expected_structured_fields() -> None:
    span = GoldenSpan(
        "P1",
        "NOTICE",
        "POSITIVE",
        "최근 3년 실적 5억원 이상",
        expected_type="PERFORMANCE_AMOUNT",
        expected_operator=">=",
        expected_value=500_000_000,
    )
    case = GoldenCase(notice_no="N1", documents=(), spans=(span,))
    chunks = [_chunk(span.quote, "NOTICE", "CHUNK-0000")]

    correct = {
        "raw": span.quote,
        "type": "PERFORMANCE_AMOUNT",
        "operator": ">=",
        "value": 500_000_000,
    }
    wrong = {**correct, "value": 50_000_000}

    assert score_case(case, chunks, chunks, canonical_requirements=[correct])["funnel"][0]["canonical"] is True
    assert score_case(case, chunks, chunks, canonical_requirements=[wrong])["funnel"][0]["canonical"] is False


def test_probabilistic_funnel_keeps_each_run_and_reports_mean() -> None:
    raw = "직접생산확인증명서를 소지한 자"
    case = GoldenCase(
        notice_no="N1",
        documents=(),
        spans=(
            GoldenSpan(
                "P1",
                "NOTICE",
                "POSITIVE",
                raw,
                expected_type="REGISTRATION_CERTIFICATION",
            ),
        ),
    )
    chunks = [_chunk(f"1. 입찰 참가자격\n{raw}", "NOTICE", "CHUNK-0000")]

    def extractor(_system, _body, _schema):
        return {
            "requirements": [
                {
                    "유형": "등록요건",
                    "raw": raw,
                    "등록인증_raw": "직접생산확인증명서",
                    "근거조항": None,
                }
            ]
        }

    report = evaluate_case_funnel(
        case,
        chunks,
        structured_extract=extractor,
        repo_root=Path("."),
        runs=2,
    )

    row = report["funnel"][0]
    assert row["extracted"] == 1
    assert row["canonical"] == 1
    assert row["judgment"] is None
    assert row["extracted_runs"] == [True, True]
    assert report["run_count"] == 2


def test_report_summary_uses_micro_averages() -> None:
    reports = [
        {
            "counts": {
                "positive_spans": 3,
                "trap_spans": 2,
                "contained_positive_spans": 3,
                "retrieved_positive_spans": 2,
                "retrieved_chunks": 4,
                "retrieved_positive_chunks": 2,
                "retrieved_trap_spans": 1,
            },
            "chunk_health": {"chunks": 10, "over_max": 2},
        },
        {
            "counts": {
                "positive_spans": 1,
                "trap_spans": 0,
                "contained_positive_spans": 1,
                "retrieved_positive_spans": 1,
                "retrieved_chunks": 2,
                "retrieved_positive_chunks": 1,
                "retrieved_trap_spans": 0,
            },
            "chunk_health": {"chunks": 5, "over_max": 0},
        },
    ]

    summary = summarize_reports(reports)

    assert summary["recall"] == 0.75
    assert summary["precision"] == 0.5
    assert summary["trap_rate"] == 0.5
    assert summary["counts"]["chunks"] == 15
