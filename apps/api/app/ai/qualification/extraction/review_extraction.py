"""후보 검토 실행을 기존 원문 슬롯 계약에 연결하는 선택적 어댑터.

복수 조항의 조건 적용/관계는 아직 legacy 슬롯으로 안전하게 표현하지 못한다.
그 경우는 슬롯을 억지로 합치지 않고 미해결로 남긴다. 기존 경로는 변경하지 않는다.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from typing import Any

from .review_execution import FIELD_NAMES, ReviewOptions, StructuredExtractor, execute_review_plan
from .review_plan import build_review_inventory, plan_review_requests


def extract_review_slots(source_blocks: Iterable[Mapping[str, Any]], *, notice_version_id: str,
                         structured_extract: StructuredExtractor,
                         options: ReviewOptions | None = None) -> dict[str, Any]:
    """원문은 서버가 고정한다. 모델은 candidate ID와 근거 표현만 선택한다.

    여기서 source block은 backend가 전달한 text 그대로여야 한다. 후보 범위를
    잘라 다시 inventory를 만들지 않는다. 빈 후보/전부 미분류도 자동 성공이 아니다.
    """
    options = options or ReviewOptions()
    blocks = [copy.deepcopy(block) for block in source_blocks]
    inventory = build_review_inventory(blocks, notice_version_id=notice_version_id)
    plan = plan_review_requests(inventory, max_body_chars=options.max_body_chars,
        max_targets_per_request=options.max_targets_per_request, neighbor_radius=options.neighbor_radius)
    execution = execute_review_plan(plan, structured_extract=structured_extract, options=options)
    by_id = {unit.candidate.candidate_id: unit for unit in inventory.units}
    source_by_location = {(block["document_id"], block["block_index"]): block for block in blocks}
    slots: list[dict[str, Any]] = []
    pending = []
    accepted_fields = []
    for decision in execution.decisions:
        if decision.status != "REQUIREMENT":
            continue
        unit = by_id[decision.candidate_id]
        candidate = unit.candidate
        reasons = set()
        if unit.reference_hints:
            reasons.add("UNRESOLVED_DOCUMENT_REFERENCE")
        for slot in decision.slots:
            if slot.basis == "CONTEXT_DEPENDENT":
                reasons.add("CONTEXT_APPLICABILITY_PENDING")
            if any(field.source_candidate_id != candidate.candidate_id for field in slot.fields):
                reasons.add("MULTI_SOURCE_REQUIREMENT_PENDING")
        # 후보 내 일부 슬롯만 채택하면 복합조건의 일부가 사라진다. 후보 전체를 보류한다.
        if reasons:
            pending.append({"candidate_id": candidate.candidate_id, "codes": sorted(reasons)})
            continue
        for slot in decision.slots:
            source = copy.deepcopy(source_by_location[(candidate.document_id, candidate.block_index)])
            # 위치는 원래 block 위치이며 문서 좌표를 모델이 새로 생성하지 않는다.
            source["text"] = candidate.text
            slot_data = {"유형": slot.type, "raw": candidate.text, "근거조항": None,
                         **{field: None for field in FIELD_NAMES},
                         "_source_chunk_id": candidate.candidate_id, "_source_blocks": [source],
                         "_review_candidate_id": candidate.candidate_id}
            for field in slot.fields:
                slot_data[field.name] = field.quote
            slots.append(slot_data)
            accepted_fields.append({"candidate_id": candidate.candidate_id, "type": slot.type,
                "field_spans": [{key: value for key, value in asdict(field).items() if key != "quote"}
                                for field in slot.fields]})
    audit = execution.audit()
    audit["adapter_pending"] = pending
    audit["accepted_slot_sources"] = accepted_fields
    # 원문과 reason은 audit에 복사하지 않되, 미해결 후보의 실제 위치를 다시 찾을 수 있다.
    audit["candidate_locators"] = [{"candidate_id": unit.candidate.candidate_id,
        "document_id": unit.candidate.document_id, "block_index": unit.candidate.block_index,
        "start_offset": unit.candidate.start_offset, "end_offset": unit.candidate.end_offset,
        "block_text_sha256": unit.candidate.block_text_sha256,
        "location": json.loads(unit.location_json)} for unit in inventory.units]
    complete = execution.coverage.coverage_status == "COMPLETE"
    if not inventory.units:
        status, notes = "failed", "검토할 원문 후보가 없습니다."
    elif not slots:
        status, notes = "partial", "판정 가능한 요건을 확보하지 못했습니다. 후보 처리 내역을 확인해야 합니다."
    elif not complete or pending or inventory.source_gaps:
        status, notes = "partial", "미응답·잘못된 참조·미해결 문맥 또는 원문 범위 공백이 있습니다."
    else:
        status, notes = "ok", ""
    # target_chunk_ids는 호환 필드명이다. 이 경로에서는 실제 전송한 검토 단위 ID를 담는다.
    sent = {key for event in execution.events if "started_at" in event
            for key in event["target_candidate_ids"]}
    return {"slots": slots, "dropped_requirements": [], "status": status, "notes": notes,
            "target_chunk_ids": [unit.candidate.candidate_id for unit in inventory.units
                                 if unit.candidate.candidate_id in sent], "review_audit": audit}
