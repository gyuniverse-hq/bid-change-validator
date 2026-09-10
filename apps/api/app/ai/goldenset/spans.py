from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


SpanKind = Literal["POSITIVE", "TRAP"]


def squash(value: str) -> str:
    """Make labels robust to PDF spacing and chunk-boundary changes."""
    return re.sub(r"\s+", "", value or "")


@dataclass(frozen=True)
class GoldenSpan:
    span_id: str
    document_id: str
    span_kind: SpanKind
    quote: str
    note: str = ""
    expected_type: str | None = None
    expected_operator: str | None = None
    expected_value: int | float | str | None = None
    expected_unit: str | None = None
    expected_period_months: float | None = None
    expected_judgment: str | None = None

    def is_in(self, text: str) -> bool:
        probe = squash(self.quote)
        return bool(probe) and probe in squash(text)
