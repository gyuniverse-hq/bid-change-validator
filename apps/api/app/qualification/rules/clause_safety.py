"""Shared deterministic source-clause safety screening."""

from __future__ import annotations

import re

_COMPLEX_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"〃|상동", "UNRESOLVED_TABLE_REFERENCE"),
    (r"공동수급|공동계약|구성원|대표사|분담이행|공동이행", "COMPOSITE_PARTY_RULE"),
    (r"대표자.*(동일|중복)|중복.*대표자|대표자.*변경등록", "REPRESENTATIVE_CONFLICT_RULE"),
    (r"\b또는\b|\b다만\b|각\s*호|중\s*하나|어느\s*하나", "ALTERNATIVE_OR_EXCEPTION_RULE"),
    (r"관계\s*법령|시행규칙|법률|규정에\s*따라|입찰무효", "LEGAL_PROCEDURAL_RULE"),
    (r"아니어야|하지\s*않아야|아닌\s*자|제외한다|제외됨", "NEGATED_RULE"),
    (r"계약.*해지|낙찰자.*결정|제한을\s*받는", "POST_AWARD_OR_RESTRICTION_RULE"),
)


def unsafe_clause_reason(raw: str) -> str | None:
    """Share conservative source-clause screening with mapping and rules."""
    return next((code for pattern, code in _COMPLEX_PATTERNS if re.search(pattern, " ".join(raw.split()))), None)
