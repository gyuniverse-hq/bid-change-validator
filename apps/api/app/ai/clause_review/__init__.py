"""Clause review — does this notice impose terms that depart from the standard?

Separate from qualification judgment, which asks whether the company may bid.
This package asks whether the contract terms in the notice are ones a bidder
should look at before committing.

Two paths, one finding contract:

- `pattern_match` catches risks with no standard figure to compare — an
  open-ended scope clause is a problem of sentence shape.
- `standard_diff` compares a figure in the notice against the figure the
  published contract rules actually state.

Both run on the same semantic chunks produced by `app.ai.chunking`, and neither
asks a model to decide anything.
"""

from .contracts import (
    VERDICT_LABELS,
    VERDICT_PRIORITY,
    ClauseFinding,
    ClauseVerdict,
    StandardReference,
)
from .embedding_fallback import make_embedding_fallback
from .pattern_match import detect_patterns
from .standard_diff import RULES, detect_standard_diff

__all__ = [
    "ClauseFinding",
    "ClauseVerdict",
    "StandardReference",
    "VERDICT_LABELS",
    "VERDICT_PRIORITY",
    "detect_patterns",
    "detect_standard_diff",
    "make_embedding_fallback",
    "RULES",
]
