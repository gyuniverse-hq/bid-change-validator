"""Canonicalization pipeline for validated legacy extraction slots."""

from __future__ import annotations

from typing import Any

from .contracts import Evidence, QualificationRequirement
from .evidence_adapter import build_evidence_from_slot
from .legacy_slots import adapt_legacy_slot


def canonicalize_validated_slot(
    slot: dict[str, Any],
    *,
    notice_version_id: str,
    key_prefix: str,
    source_type: str = "NOTICE_DOCUMENT",
    case_id: str | None = None,
) -> tuple[list[QualificationRequirement], list[Evidence], list[dict[str, Any]]]:
    """Convert one source-grounded legacy slot to canonical objects.

    One extracted slot may become multiple atomic requirements, but they all point
    to the same source-grounded Evidence item unless a later extractor supplies
    finer-grained provenance.
    """
    requirements, diagnostics = adapt_legacy_slot(
        slot,
        notice_version_id=notice_version_id,
        key_prefix=key_prefix,
    )
    if not requirements:
        return [], [], diagnostics

    evidence_key = f"{key_prefix}-EVD"
    evidence = build_evidence_from_slot(
        slot,
        evidence_key=evidence_key,
        source_type=source_type,
        notice_version_id=notice_version_id,
        case_id=case_id,
    )

    linked_requirements: list[QualificationRequirement] = []
    for requirement in requirements:
        linked_requirements.append(
            requirement.model_copy(update={"evidence_keys": [evidence_key]})
        )

    return linked_requirements, [evidence], diagnostics


def canonicalize_validated_slots(
    slots: list[dict[str, Any]],
    *,
    notice_version_id: str,
    source_type: str = "NOTICE_DOCUMENT",
    case_id: str | None = None,
    key_prefix: str = "REQ",
) -> dict[str, Any]:
    """Canonicalize multiple accepted slots with stable per-slot keys."""
    requirements: list[QualificationRequirement] = []
    evidence: list[Evidence] = []
    diagnostics: list[dict[str, Any]] = []

    for index, slot in enumerate(slots, start=1):
        slot_prefix = f"{key_prefix}-{index:03d}"
        slot_requirements, slot_evidence, slot_diagnostics = canonicalize_validated_slot(
            slot,
            notice_version_id=notice_version_id,
            key_prefix=slot_prefix,
            source_type=source_type,
            case_id=case_id,
        )
        requirements.extend(slot_requirements)
        evidence.extend(slot_evidence)
        diagnostics.extend(slot_diagnostics)

    return {
        "requirements": requirements,
        "evidence": evidence,
        "diagnostics": diagnostics,
    }
