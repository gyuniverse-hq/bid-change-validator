"""Canonicalization pipeline for validated legacy extraction slots."""

from __future__ import annotations

from typing import Any

from ..contracts import Evidence, QualificationRequirement
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

    evidence_key = f"{key_prefix}-EVD"
    evidence = build_evidence_from_slot(
        slot,
        evidence_key=evidence_key,
        source_type=source_type,
        notice_version_id=notice_version_id,
        case_id=case_id,
    )

    if not requirements:
        # 닫힌 유형으로 매핑되지 않았다고 근거까지 버리지 않는다. 예전에는 여기서
        # 빈 목록을 돌려줘서 원문 위치가 통째로 사라졌고, 사용자 입장에서
        # "확인했는데 판정 대상이 아님" 과 "아예 못 봤음" 이 구분되지 않았다.
        #
        # 실측: 실제 공고에서 「국가계약법 시행령」제12조 자격, 부정당업체 미지정,
        # 계약사무규칙 제15조 제한사유, 공동수급·하도급 불허 4건이 이렇게 사라졌다.
        # 넷 다 판정하지 않는 것이 맞지만, 기록이 없어지는 것은 맞지 않다.
        return (
            [],
            [evidence],
            [{**item, "evidence_keys": [evidence_key]} for item in diagnostics],
        )

    linked_requirements: list[QualificationRequirement] = []
    for requirement in requirements:
        linked_requirements.append(
            requirement.model_copy(update={"evidence_keys": [evidence_key]})
        )

    return (
        linked_requirements,
        [evidence],
        [{**item, "evidence_keys": [evidence_key]} for item in diagnostics],
    )


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
