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

# The vocabulary the team shares — DB column, UI filter, and this pipeline all
# name a risk the same way. `rule_id` stays internal: it says which check ran,
# and several checks can answer to one type.
RiskType = Literal[
    "WARRANTY_PERIOD",  # 하자담보 기간
    "LATE_PENALTY",  # 지체상금 상한
    "LATE_PENALTY_RATE",  # 지체상금 요율 — 근거 법령이 상한과 다르다
    "COPYRIGHT_OWNERSHIP",  # 저작권(지식재산권) 귀속
    "ACCEPTANCE_CRITERIA",  # 검사·검수
    "SCOPE_AMBIGUITY",  # 과업범위 모호 (포괄조항 포함)
    "TERMINATION_CONDITION",  # 계약해지 요건
    "PAYMENT_TERMS",  # 대금지급
    "LIABILITY_SCOPE",  # 손해배상
]

# None means the check runs but has no agreed type yet, so its finding is kept
# with the type left empty rather than being dropped.
RISK_TYPE_BY_RULE: dict[str, RiskType | None] = {
    "warranty_period": "WARRANTY_PERIOD",
    "penalty_cap": "LATE_PENALTY",
    "penalty_rate": "LATE_PENALTY_RATE",
    "ip_ownership": "COPYRIGHT_OWNERSHIP",
    "inspection_period": "ACCEPTANCE_CRITERIA",
    "open_ended_scope": "SCOPE_AMBIGUITY",
    "termination_threshold": "TERMINATION_CONDITION",
    "payment_period": "PAYMENT_TERMS",
    "liability_scope": "LIABILITY_SCOPE",
    "warranty_bond_rate": None,
}

RISK_TYPE_LABELS: dict[RiskType, str] = {
    "WARRANTY_PERIOD": "하자담보 기간",
    "LATE_PENALTY": "지체상금 상한",
    "LATE_PENALTY_RATE": "지체상금 요율",
    "COPYRIGHT_OWNERSHIP": "저작권 귀속",
    "ACCEPTANCE_CRITERIA": "검사·검수",
    "SCOPE_AMBIGUITY": "과업범위 모호",
    "TERMINATION_CONDITION": "계약해지 요건",
    "PAYMENT_TERMS": "대금지급",
    "LIABILITY_SCOPE": "손해배상",
}

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

    @property
    def risk_type_code(self) -> RiskType | None:
        """The shared vocabulary value for this finding, or None when it has none."""
        return RISK_TYPE_BY_RULE.get(self.rule_id)


def overlapping_categories(
    finding: ClauseFinding, findings: list[ClauseFinding]
) -> tuple[list[RiskType], list[str]]:
    """Return every agreed risk type detected in the same source clause.

    One sentence can legitimately produce several findings.  The usual example is
    a late-penalty sentence containing both a daily rate and a total cap.  Findings
    stay separate because their standards and verdicts differ, but API consumers
    also need the complete category set instead of guessing it from display text.
    """

    def same_source(other: ClauseFinding) -> bool:
        if other is finding:
            return True
        if finding.notice_version_id != other.notice_version_id:
            return False
        if finding.chunk_id and other.chunk_id and finding.chunk_id != other.chunk_id:
            return False
        if finding.clause_label and other.clause_label:
            if finding.clause_label != other.clause_label:
                return False
        left = " ".join((finding.excerpt or finding.matched_text or "").split())
        right = " ".join((other.excerpt or other.matched_text or "").split())
        if left and right:
            return left == right or left in right or right in left
        # With no comparable source text, sharing a chunk is the strongest safe
        # evidence available.  Never merge location-less synthetic findings.
        return bool(finding.chunk_id and finding.chunk_id == other.chunk_id)

    # The scalar `risk_type`/`category` pair must describe this finding, so keep
    # its code first even when callers pass the full result list in another order.
    risk_types: list[RiskType] = []
    for item in [finding, *(item for item in findings if item is not finding)]:
        code = item.risk_type_code
        if code is not None and same_source(item) and code not in risk_types:
            risk_types.append(code)
    return risk_types, [RISK_TYPE_LABELS[code] for code in risk_types]


def excerpt(text: str | None, limit: int = 200) -> str | None:
    """Collapse whitespace and cut to a readable length for display."""
    if not text:
        return None
    collapsed = " ".join(text.split())
    return collapsed[:limit] + ("…" if len(collapsed) > limit else "")
