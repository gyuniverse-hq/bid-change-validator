from __future__ import annotations

import statistics
from typing import Any

from .fixtures import GoldenCase
from .spans import GoldenSpan, squash


def _has_span(chunk: dict[str, Any], span) -> bool:
    source_ids = {
        str(block.get("document_id")) for block in chunk.get("source_blocks", [])
    }
    return span.document_id in source_ids and span.is_in(chunk.get("text") or "")


def _read(item: Any, field: str) -> Any:
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def _raw_matches(span: GoldenSpan, item: Any) -> bool:
    label = squash(span.quote)
    raw = squash(str(_read(item, "raw") or ""))
    return bool(label and raw) and (label in raw or (len(raw) >= 20 and raw in label))


def _canonical_matches(span: GoldenSpan, item: Any) -> bool:
    if not _raw_matches(span, item):
        return False
    expected = {
        "type": span.expected_type,
        "operator": span.expected_operator,
        "value": span.expected_value,
        "unit": span.expected_unit,
        "period_months": span.expected_period_months,
    }
    return all(value is None or _read(item, field) == value for field, value in expected.items())


def score_case(
    case: GoldenCase,
    chunks: list[dict[str, Any]],
    retrieved: list[dict[str, Any]],
    *,
    extracted_slots: list[Any] | None = None,
    canonical_requirements: list[Any] | None = None,
    judgments: list[Any] | None = None,
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
        extracted = (
            None
            if extracted_slots is None
            else any(_raw_matches(span, item) for item in extracted_slots)
        )
        matching_requirements = (
            []
            if canonical_requirements is None
            else [item for item in canonical_requirements if _canonical_matches(span, item)]
        )
        canonical = None if canonical_requirements is None else bool(matching_requirements)
        judgment = None
        if span.expected_judgment is not None and judgments is not None:
            requirement_keys = {
                _read(item, "requirement_key") for item in matching_requirements
            }
            judgment = any(
                _read(item, "requirement_key") in requirement_keys
                and _read(item, "status") == span.expected_judgment
                for item in judgments
            )
        rows.append(
            {
                "span_id": span.span_id,
                "note": span.note,
                "contained": contained,
                "retrieved": selected,
                "extracted": extracted,
                "canonical": canonical,
                "judgment": judgment,
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
        "counts": {
            "positive_spans": len(positives),
            "trap_spans": len(traps),
            "contained_positive_spans": sum(row["contained"] for row in rows),
            "retrieved_positive_spans": retrieved_positive_spans,
            "retrieved_chunks": len(retrieved),
            "retrieved_positive_chunks": retrieved_positive_chunks,
            "retrieved_trap_spans": retrieved_traps,
        },
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
