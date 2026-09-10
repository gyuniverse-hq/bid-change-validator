"""Run the probabilistic extraction portion of the quality funnel."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..qualification.canonical.canonicalize import canonicalize_validated_slots
from ..qualification.extraction.requirement_extraction import (
    StructuredExtractor,
    extract_legacy_slots,
    select_eligibility_chunks,
)
from ...qualification.rules.judgment import CompanyProfileSnapshot, judge_requirements
from ..normalization import normalize_value
from .fixtures import GoldenCase
from .scoring import score_case


def _normalize_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for source in slots:
        slot = dict(source)
        for raw_field, normalized_field in (
            ("금액_raw", "금액_norm"),
            ("기간_raw", "기간_norm"),
            ("인원_raw", "인원_norm"),
        ):
            if slot.get(raw_field):
                slot[normalized_field] = normalize_value(str(slot[raw_field]))
        normalized.append(slot)
    return normalized


def _load_profile(
    case: GoldenCase,
    *,
    repo_root: Path,
) -> CompanyProfileSnapshot | None:
    if not case.profile_path:
        return None
    payload = json.loads((repo_root / case.profile_path).read_text(encoding="utf-8"))
    return CompanyProfileSnapshot.model_validate(payload)


def _mean(values: list[bool | None]) -> float | None:
    measured = [value for value in values if value is not None]
    return None if not measured else sum(measured) / len(measured)


def evaluate_case_funnel(
    case: GoldenCase,
    chunks: list[dict[str, Any]],
    *,
    structured_extract: StructuredExtractor,
    repo_root: Path,
    runs: int = 3,
) -> dict[str, Any]:
    """Measure extraction, canonicalization, and optional judgment over N runs."""
    if runs < 1:
        raise ValueError("runs must be at least 1")

    retrieved = select_eligibility_chunks(chunks)
    profile = _load_profile(case, repo_root=repo_root)
    run_reports: list[dict[str, Any]] = []
    run_metadata: list[dict[str, Any]] = []

    for _ in range(runs):
        extraction = extract_legacy_slots(
            chunks,
            structured_extract=structured_extract,
        )
        slots = _normalize_slots(list(extraction.get("slots") or []))
        canonicalized = canonicalize_validated_slots(
            slots,
            notice_version_id=f"golden:{case.notice_no}",
        )
        requirements = list(canonicalized["requirements"])
        judgments: list[Any] | None = None
        if profile is not None and case.reference_date:
            judgments = judge_requirements(
                requirements,
                profile,
                preflight_case_id=f"golden:{case.notice_no}",
                reference_date=date.fromisoformat(case.reference_date),
                analysis_status=(
                    "SUCCEEDED" if extraction.get("status") == "ok" else "PARTIAL"
                ),
            ).judgments

        run_reports.append(
            score_case(
                case,
                chunks,
                retrieved,
                extracted_slots=slots,
                canonical_requirements=requirements,
                judgments=judgments,
            )
        )
        run_metadata.append(
            {
                "status": extraction.get("status"),
                "accepted_slots": len(slots),
                "canonical_requirements": len(requirements),
                "dropped_requirements": len(extraction.get("dropped_requirements") or []),
            }
        )

    report = score_case(case, chunks, retrieved)
    for index, row in enumerate(report["funnel"]):
        for stage in ("extracted", "canonical", "judgment"):
            values = [item["funnel"][index][stage] for item in run_reports]
            row[stage] = _mean(values)
            row[f"{stage}_runs"] = values

    report["probabilistic_runs"] = run_metadata
    report["run_count"] = runs
    return report
