"""Adapter from extraction slot shape to canonical requirements.

The extraction layer keeps human-readable Korean slot types as an internal
interface. Production maps those slots into the closed seven-type canonical
taxonomy. Unsupported/ambiguous slots become diagnostics instead of being
forced into a judgment category.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import QualificationRequirement

_COUNT_RE = re.compile(r"(\d+)\s*(?:건|회)\s*(이상|초과|이하|미만)?")


def _op(word: str | None) -> str | None:
    return {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}.get(word)


def adapt_legacy_slot(
    slot: dict[str, Any],
    *,
    notice_version_id: str,
    key_prefix: str,
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """Map one validated extraction slot into zero or more canonical requirements."""
    slot_type = slot.get("유형")
    raw = (slot.get("raw") or "").strip()
    diagnostics: list[dict[str, Any]] = []
    requirements: list[QualificationRequirement] = []
    group_key = f"{key_prefix}-GROUP"

    def add(
        suffix: str,
        req_type: str,
        *,
        operator: str | None = None,
        value: int | float | str | None = None,
        unit: str | None = None,
        period_months: float | None = None,
        scope: dict[str, Any] | None = None,
    ) -> None:
        requirements.append(
            QualificationRequirement(
                requirement_key=f"{key_prefix}-{suffix}",
                requirement_group_key=group_key,
                group_operator="ALL_OF",
                notice_version_id=notice_version_id,
                type=req_type,
                operator=operator,
                value=value,
                unit=unit,
                period_months=period_months,
                scope=scope or {},
                raw=raw,
            )
        )

    if slot_type == "실적요건":
        amount = slot.get("금액_norm") or {}
        period = slot.get("기간_norm") or {}
        period_months = period.get("value") if period.get("parse_status") == "success" else None

        if amount.get("parse_status") == "success" and amount.get("value") is not None:
            add(
                "AMOUNT",
                "PERFORMANCE_AMOUNT",
                operator=amount.get("op"),
                value=amount.get("value"),
                unit=amount.get("unit") or "KRW",
                period_months=period_months,
                scope={"aggregation": "UNSPECIFIED"},
            )

        count_match = _COUNT_RE.search(raw)
        if count_match:
            add(
                "COUNT",
                "PERFORMANCE_COUNT",
                operator=_op(count_match.group(2)) or ">=",
                value=int(count_match.group(1)),
                unit="COUNT",
                period_months=period_months,
            )

        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add(
                "EXPERIENCE",
                "EXPERIENCE_FIELD",
                value=experience_field,
                period_months=period_months,
                scope={"source": "PERFORMANCE"},
            )

        if not requirements:
            diagnostics.append({"code": "UNMAPPED_PERFORMANCE", "raw": raw})

    elif slot_type == "경험분야요건":
        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add("EXPERIENCE", "EXPERIENCE_FIELD", value=experience_field)
        else:
            diagnostics.append({"code": "UNMAPPED_EXPERIENCE_FIELD", "raw": raw})

    elif slot_type == "업종요건":
        industry = (slot.get("업종_raw") or "").strip()
        if industry:
            add("INDUSTRY", "INDUSTRY", value=industry)
        else:
            diagnostics.append({"code": "UNMAPPED_INDUSTRY", "raw": raw})

    elif slot_type == "인력요건":
        add("STAFF", "STAFF")
    elif slot_type in {"인증요건", "면허요건"}:
        add("CERT", "REGISTRATION_CERTIFICATION")
    elif slot_type == "지역요건":
        add("REGION", "REGION")
    elif slot_type == "기타요건":
        diagnostics.append({"code": "UNMAPPED_REQUIREMENT", "raw": raw})
    else:
        diagnostics.append({"code": "UNKNOWN_LEGACY_TYPE", "type": slot_type, "raw": raw})

    return requirements, diagnostics
