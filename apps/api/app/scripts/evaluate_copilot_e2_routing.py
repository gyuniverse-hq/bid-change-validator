"""Evaluate the E2 semantic router on the frozen 100-question routing set.

This script measures only semantic intent classification. It does not connect to
the product DB, run qualification judgment, retrieve documents, or execute any
write action.

Usage:
    python -m apps.api.app.scripts.evaluate_copilot_e2_routing --validate-only
    OPENAI_API_KEY=... python -m apps.api.app.scripts.evaluate_copilot_e2_routing

The output is JSON so it can be archived without reformatting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from apps.api.app.copilot.semantic_router import SemanticRouter


def load_dataset() -> tuple[Path, dict]:
    root = Path(__file__).resolve().parents[4]
    path = root / "apps/api/eval/copilot_e2_routing.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if data.get("count") != 100 or not isinstance(cases, list) or len(cases) != 100:
        raise RuntimeError("E2 routing dataset must contain exactly 100 frozen cases")
    ids = [case.get("scenario_id") for case in cases]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise RuntimeError("E2 routing scenario IDs must be unique and non-empty")
    allowed = {"DOCUMENT_QA", "QUALIFICATION_SUMMARY", "CHANGED_NOTICE"}
    if any(case.get("expected_intent") not in allowed for case in cases):
        raise RuntimeError("E2 routing dataset contains an unexpected expected_intent")
    return path, data


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    path, data = load_dataset()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.validate_only:
        print(json.dumps({
            "status": "dataset_valid",
            "dataset": str(path),
            "fixture_sha256": digest,
            "count": 100,
            "model_calls": 0,
        }, ensure_ascii=False, indent=2))
        return 0

    if not os.getenv("OPENAI_API_KEY"):
        print(json.dumps({
            "status": "not_run",
            "reason": "OPENAI_API_KEY is not configured",
            "fixture_sha256": digest,
            "count": 100,
            "model_calls": 0,
        }, ensure_ascii=False, indent=2))
        return 2

    router = SemanticRouter()
    if not router.available:
        raise RuntimeError("semantic router provider is unavailable")

    rows = []
    latencies = []
    by_group: dict[str, Counter] = defaultdict(Counter)
    actual_distribution = Counter()

    for case in data["cases"]:
        started = time.perf_counter()
        route = router.classify(case["question"])
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        actual = route.intent if route is not None else "UNKNOWN"
        matched = actual == case["expected_intent"]
        actual_distribution[actual] += 1
        by_group[case["group"]]["total"] += 1
        by_group[case["group"]]["matched"] += int(matched)
        rows.append({
            "scenario_id": case["scenario_id"],
            "group": case["group"],
            "expected_intent": case["expected_intent"],
            "actual_intent": actual,
            "matched": matched,
            "confidence": route.confidence if route is not None else None,
            "subject": route.subject if route is not None else None,
            "task": route.task if route is not None else None,
            "needs_context": route.needs_context if route is not None else None,
            "latency_ms": round(elapsed_ms, 2),
        })

    matched = sum(row["matched"] for row in rows)
    groups = {}
    for group, counts in sorted(by_group.items()):
        groups[group] = {
            "total": counts["total"],
            "matched": counts["matched"],
            "accuracy": round(counts["matched"] / counts["total"], 4),
        }

    print(json.dumps({
        "status": "completed",
        "evaluation_scope": "semantic intent classification only; not product task completion",
        "fixture_sha256": digest,
        "count": len(rows),
        "matched": matched,
        "accuracy": round(matched / len(rows), 4),
        "groups": groups,
        "actual_distribution": dict(actual_distribution),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "mean": round(statistics.fmean(latencies), 2),
        },
        "rows": rows,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
