from __future__ import annotations

import statistics
from typing import Any

from .fixtures import GoldenCase


def _has_span(chunk: dict[str, Any], span) -> bool:
    source_ids = {
        str(block.get("document_id")) for block in chunk.get("source_blocks", [])
    }
    return span.document_id in source_ids and span.is_in(chunk.get("text") or "")


def score_case(
    case: GoldenCase,
    chunks: list[dict[str, Any]],
    retrieved: list[dict[str, Any]],
    *,
    max_chars: int = 1800,
    budget_chars: int = 32_000,
) -> dict[str, Any]:
    lengths = [len(chunk.get("text") or "") for chunk in chunks]
    positives = [span for span in case.spans if span.span_kind == "POSITIVE"]
    traps = [span for span in case.spans if span.span_kind == "TRAP"]

    rows = []
    for span in positives:
        contained = any(_has_span(chunk, span) for chunk in chunks)
        selected = any(_has_span(chunk, span) for chunk in retrieved)
        rows.append(
            {
                "span_id": span.span_id,
                "note": span.note,
                "contained": contained,
                "retrieved": selected,
                "extracted": None,
                "canonical": None,
            }
        )

    retrieved_positive_chunks = sum(
        any(_has_span(chunk, span) for span in positives) for chunk in retrieved
    )
    retrieved_traps = sum(
        any(_has_span(chunk, span) for chunk in retrieved) for span in traps
    )
    retrieved_positive_spans = sum(row["retrieved"] for row in rows)
    return {
        "notice_no": case.notice_no,
        "chunk_health": {
            "chunks": len(chunks),
            "median_chars": statistics.median(lengths) if lengths else 0,
            "pct_under_50": sum(length < 50 for length in lengths) / len(lengths)
            if lengths
            else 0,
            "over_max": sum(length > max_chars for length in lengths),
            "max_chars": max(lengths, default=0),
            "span_containment": sum(row["contained"] for row in rows) / len(rows)
            if rows
            else None,
        },
        "retrieval": {
            "retrieved_chunks": len(retrieved),
            "recall": retrieved_positive_spans / len(positives) if positives else None,
            "precision": retrieved_positive_chunks / len(retrieved) if retrieved else None,
            "trap_rate": retrieved_traps / len(traps) if traps else None,
            "budget_utilisation": min(
                1.0, sum(len(chunk.get("text") or "") for chunk in retrieved) / budget_chars
            ),
            "heading_only_rate": sum(
                len((chunk.get("text") or "").strip()) < 40 for chunk in retrieved
            )
            / len(retrieved)
            if retrieved
            else None,
        },
        "funnel": rows,
    }
