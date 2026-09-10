from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..ai.goldenset import evaluate_case_funnel, load_case_chunks, load_cases, score_case
from ..ai.qualification.extraction.requirement_extraction import select_eligibility_chunks


REPO_ROOT = Path(__file__).resolve().parents[4]
CHUNKERS = ("default", "hygienic")


def _not_lower(candidate: float | None, baseline: float | None) -> bool:
    return baseline is None or (candidate is not None and candidate >= baseline)


def _not_higher(candidate: float | None, baseline: float | None) -> bool:
    return baseline is None or (candidate is not None and candidate <= baseline)


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def summarize_reports(reports: list[dict]) -> dict:
    """Micro-average label metrics so large and small notices count fairly."""
    totals = {
        key: sum(int(report["counts"][key]) for report in reports)
        for key in (
            "positive_spans",
            "trap_spans",
            "contained_positive_spans",
            "retrieved_positive_spans",
            "retrieved_chunks",
            "retrieved_positive_chunks",
            "retrieved_trap_spans",
        )
    }
    totals["chunks"] = sum(report["chunk_health"]["chunks"] for report in reports)
    totals["oversized_chunks"] = sum(
        report["chunk_health"]["over_max"] for report in reports
    )
    return {
        "counts": totals,
        "span_containment": _ratio(
            totals["contained_positive_spans"], totals["positive_spans"]
        ),
        "recall": _ratio(
            totals["retrieved_positive_spans"], totals["positive_spans"]
        ),
        "precision": _ratio(
            totals["retrieved_positive_chunks"], totals["retrieved_chunks"]
        ),
        "trap_rate": _ratio(totals["retrieved_trap_spans"], totals["trap_spans"]),
    }


def build_report(
    goldenset: Path,
    *,
    chunker: str = "default",
    structured_extract=None,
    runs: int = 3,
) -> dict:
    cases = load_cases(goldenset)
    reports = []
    for case in cases:
        chunks = load_case_chunks(case, repo_root=REPO_ROOT, chunker=chunker)
        retrieved = select_eligibility_chunks(chunks)
        reports.append(
            score_case(case, chunks, retrieved)
            if structured_extract is None
            else evaluate_case_funnel(
                case,
                chunks,
                structured_extract=structured_extract,
                repo_root=REPO_ROOT,
                runs=runs,
            )
        )
    return {
        "goldenset": goldenset.name,
        "chunker": chunker,
        "case_count": len(reports),
        "summary": summarize_reports(reports),
        "cases": reports,
    }


def build_comparison(
    goldenset: Path,
    *,
    structured_extract=None,
    runs: int = 3,
) -> dict:
    """Run both deterministic chunkers against exactly the same labels."""
    reports = {
        chunker: build_report(
            goldenset,
            chunker=chunker,
            structured_extract=structured_extract,
            runs=runs,
        )
        for chunker in CHUNKERS
    }
    gates = []
    for baseline, candidate in zip(
        reports["default"]["cases"], reports["hygienic"]["cases"], strict=True
    ):
        baseline_retrieval = baseline["retrieval"]
        candidate_retrieval = candidate["retrieval"]
        passed = {
            "span_containment_not_lower": _not_lower(
                candidate["chunk_health"]["span_containment"],
                baseline["chunk_health"]["span_containment"],
            ),
            "recall_not_lower": _not_lower(
                candidate_retrieval["recall"], baseline_retrieval["recall"]
            ),
            "precision_not_lower": _not_lower(
                candidate_retrieval["precision"], baseline_retrieval["precision"]
            ),
            "trap_rate_not_higher": _not_higher(
                candidate_retrieval["trap_rate"], baseline_retrieval["trap_rate"]
            ),
            "no_oversized_chunks": candidate["chunk_health"]["over_max"] == 0,
        }
        gates.append(
            {
                "notice_no": baseline["notice_no"],
                "passed": passed,
                "eligible_for_rollout": all(passed.values()),
            }
        )
    return {
        "goldenset": goldenset.name,
        "reports": reports,
        "rollout_gates": gates,
        "eligible_for_rollout": bool(gates)
        and all(item["eligible_for_rollout"] for item in gates),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic qualification retrieval report")
    parser.add_argument("--goldenset", type=Path, required=True)
    parser.add_argument("--retriever", choices=("default",), default="default")
    parser.add_argument("--chunker", choices=CHUNKERS, default="default")
    parser.add_argument("--compare-chunkers", action="store_true")
    parser.add_argument("--with-extraction", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    extractor = None
    if args.with_extraction:
        try:
            from dotenv import load_dotenv

            load_dotenv(REPO_ROOT / ".env")
        except ImportError:
            pass
        from ..ai.providers.openai import OpenAIStructuredExtractor

        extractor = OpenAIStructuredExtractor(model=args.model)
        if not extractor.available:
            parser.error("--with-extraction requires OPENAI_API_KEY")

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    report = (
        build_comparison(
            args.goldenset,
            structured_extract=extractor,
            runs=args.runs,
        )
        if args.compare_chunkers
        else build_report(
            args.goldenset,
            chunker=args.chunker,
            structured_extract=extractor,
            runs=args.runs,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
