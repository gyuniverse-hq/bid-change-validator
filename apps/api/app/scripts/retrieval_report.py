from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..ai.goldenset import load_case_chunks, load_cases, score_case
from ..ai.requirement_extraction import select_eligibility_chunks


REPO_ROOT = Path(__file__).resolve().parents[4]


def build_report(goldenset: Path) -> dict:
    cases = load_cases(goldenset)
    reports = []
    for case in cases:
        chunks = load_case_chunks(case, repo_root=REPO_ROOT)
        retrieved = select_eligibility_chunks(chunks)
        reports.append(score_case(case, chunks, retrieved))
    return {"goldenset": goldenset.name, "case_count": len(reports), "cases": reports}


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic qualification retrieval report")
    parser.add_argument("--goldenset", type=Path, required=True)
    parser.add_argument("--retriever", choices=("default",), default="default")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report(args.goldenset)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
