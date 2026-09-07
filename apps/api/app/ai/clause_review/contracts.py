"""Canonical output contract for clause review.

Clause review answers a different question from qualification judgment. Judgment
asks "can this company bid"; clause review asks "does this notice put terms on
the bidder that depart from the standard contract conditions". Both are grounded
in source text, so both are expressed as contracts rather than loose dicts.

Two detection paths produce the same finding shape:

- STANDARD_DIFF compares a figure in the notice against the figure the government
  contract rules actually state (하자보수 기간, 지체상금 상한 …).
- PATTERN_MATCH covers risks with no counterpart figure to compare — an open-ended
  scope clause is a problem of sentence *shape*, not of a value being too large.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ClauseVerdict = Literal[
    "NEEDS_REVIEW",  # 확인 필요 — departs from the standard, or opens the scope
    "COMPLIANT",  # 적합 — within the standard
    "UNDETERMINED",  # 확인 불가 — the clause is present but could not be settled
]

DetectionMethod = Literal["STANDARD_DIFF", "PATTERN_MATCH"]

MatchedVia = Literal[
    "REGEX",  # found by the lexicon patterns, no model involved
    "EMBEDDING_LLM",  # found by embedding search with model-quoted source text
    "STANDARD_UNRESOLVED",  # the standard figure itself could not be read
]

# Display wording. The pipeline speaks the contract vocabulary; reports and the
# UI render these, so the mapping lives in one place.
VERDICT_LABELS: dict[str, str] = {
    "NEEDS_REVIEW": "확인 필요",
    "COMPLIANT": "적합",
    "UNDETERMINED": "확인 불가",
}

# Ordering used when several chunks produce a finding for the same rule: the most
# actionable verdict wins, and "we could not tell" comes last.
VERDICT_PRIORITY: dict[str, int] = {"NEEDS_REVIEW": 0, "COMPLIANT": 1, "UNDETERMINED": 2}


class StandardReference(BaseModel):
    """The standard clause a finding was compared against.

    `value` and `value_raw` are what the comparison actually used, read out of the
    published rules rather than hard-coded, so an audit can retrace the number to
    the sentence it came from.
    """

    source: str | None = None
    clause_ref: str | None = None
    description: str | None = None
    value: float | None = None
    value_raw: str | None = None
    unit: str | None = None
    note: str | None = None
    text_excerpt: str | None = None
    chapter: str | None = None


class ClauseFinding(BaseModel):
    """One reviewed clause: what was found, where, and what it was measured against."""

    rule_id: str
    risk_type: str
    detection_method: DetectionMethod
    matched_via: MatchedVia = "REGEX"
    verdict: ClauseVerdict
    reason: str
    # Which sentence shape fired, for pattern findings.
    form: str | None = None
    matched_text: str | None = None

    notice_version_id: str | None = None
    chunk_id: str | None = None
    clause_label: str | None = None
    excerpt: str | None = None

    # The normalized figure read out of the notice, when the rule compares one.
    notice_value: float | None = None
    notice_value_raw: str | None = None
    notice_value_unit: str | None = None

    standard: StandardReference | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABELS[self.verdict]


def excerpt(text: str | None, limit: int = 200) -> str | None:
    """Collapse whitespace and cut to a readable length for display."""
    if not text:
        return None
    collapsed = " ".join(text.split())
    return collapsed[:limit] + ("…" if len(collapsed) > limit else "")
