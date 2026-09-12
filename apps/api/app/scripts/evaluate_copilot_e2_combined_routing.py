"""Evaluate the actual E1 -> deterministic -> E2 semantic routing order.

Unlike `evaluate_copilot_e2_routing`, which measures the semantic classifier in
isolation, this evaluator mirrors the product read-routing order for the frozen
100-question set:

    frontend bounded E1 alias
      -> backend deterministic route_intent
      -> semantic resolver only for UNKNOWN reads

It does not connect to the DB, retrieve documents, run judgments or execute writes.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID

from apps.api.app.copilot.chat import CopilotChatRequest, route_intent
from apps.api.app.copilot.intent_resolver import resolve_intent
from apps.api.app.copilot.semantic_router import SemanticRouter
from apps.api.app.scripts.evaluate_copilot_e2_routing import (
    emit,
    load_dataset,
    load_local_env,
    percentile,
    repository_root,
)

DUMMY_CASE_ID = UUID("00000000-0000-0000-0000-000000000001")


def compact_question(text: str) -> str:
    return re.sub(r"[?.!。？！]", "", re.sub(r"\s+", "", text))


def infer_e1_intent(question: str) -> str | None:
    """Exact Python mirror of apps/web/lib/copilot-conversation.ts E1 aliases.

    Keep intentionally bounded. If this grows, change the product implementation
    and this evaluator in the same commit and protect both with regression tests.
    """
    text = compact_question(question)
    company_subject = any(term in text for term in ("우리", "저희", "당사"))
    if company_subject and any(term in text for term in (
        "참가할수", "참여할수", "넣어도돼", "넣을수", "지원할수",
    )):
        return "QUALIFICATION_SUMMARY"
    if any(term in text for term in (
        "무엇이바뀌", "뭐가바뀌", "바뀐내용", "달라진내용", "변경내용",
    )):
        return "CHANGED_NOTICE"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = repository_root()
    loaded_env_files = load_local_env(root)
    path, data = load_dataset()

    if args.validate_only:
        payload = {
            "status": "dataset_valid",
            "evaluation_scope": "combined E1 + deterministic + E2 semantic intent routing",
            "dataset": str(path),
            "count": 100,
            "local_env_files_found": loaded_env_files,
        }
        emit(payload, args.output)
        return 0

    router = SemanticRouter()
    if not router.available:
        payload = {
            "status": "not_run",
            "reason": "semantic router provider is unavailable after loading local env files",
            "count": 100,
            "local_env_files_found": loaded_env_files,
        }
        emit(payload, args.output)
        return 2

    rows = []
    latencies = []
    by_group: dict[str, Counter] = defaultdict(Counter)
    route_sources = Counter()
    actual_distribution = Counter()
    semantic_calls = 0

    for case in data["cases"]:
        question = case["question"]
        explicit = infer_e1_intent(question)
        request = CopilotChatRequest(
            case_id=DUMMY_CASE_ID,
            message=question,
            intent=explicit,
        )
        deterministic = route_intent(request)

        started = time.perf_counter()
        result = resolve_intent(
            deterministic_intent=deterministic,
            message=question,
            classifier=router,
            explicit_intent=explicit,
            has_user_input=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)

        if result.route_source == "SEMANTIC" or (
            deterministic == "UNKNOWN" and explicit is None and result.semantic is not None
        ):
            semantic_calls += 1

        actual = result.intent
        matched = actual == case["expected_intent"]
        route_sources[result.route_source] += 1
        actual_distribution[actual] += 1
        by_group[case["group"]]["total"] += 1
        by_group[case["group"]]["matched"] += int(matched)
        rows.append({
            "scenario_id": case["scenario_id"],
            "group": case["group"],
            "question": question,
            "expected_intent": case["expected_intent"],
            "e1_explicit_intent": explicit,
            "deterministic_intent": deterministic,
            "route_source": result.route_source,
            "actual_intent": actual,
            "matched": matched,
            "semantic_intent": result.semantic.intent if result.semantic else None,
            "semantic_confidence": result.semantic.confidence if result.semantic else None,
            "semantic_subject": result.semantic.subject if result.semantic else None,
            "semantic_task": result.semantic.task if result.semantic else None,
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

    semantic_latencies = [
        row["latency_ms"] for row in rows
        if row["route_source"] in ("SEMANTIC", "FALLBACK") and row["deterministic_intent"] == "UNKNOWN"
    ]
    payload = {
        "status": "completed",
        "evaluation_scope": "combined E1 frontend alias + backend deterministic + E2 semantic fallback; routing only",
        "count": len(rows),
        "matched": matched,
        "accuracy": round(matched / len(rows), 4),
        "groups": groups,
        "route_sources": dict(route_sources),
        "actual_distribution": dict(actual_distribution),
        "semantic_calls": semantic_calls,
        "semantic_call_rate": round(semantic_calls / len(rows), 4),
        "resolver_latency_ms": {
            "all_p50": round(statistics.median(latencies), 2),
            "semantic_p50": round(statistics.median(semantic_latencies), 2) if semantic_latencies else None,
            "semantic_p95": round(percentile(semantic_latencies, 0.95), 2) if semantic_latencies else None,
        },
        "rows": rows,
    }
    emit(payload, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
