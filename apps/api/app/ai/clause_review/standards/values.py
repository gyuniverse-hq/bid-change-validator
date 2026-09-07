"""Reading the comparison thresholds out of the published rules themselves.

The figures a notice is checked against — 하자보수 1년, 지체상금 상한 100분의 30 —
are **not written in this codebase**. They are extracted from the rule text on
every run, and the only thing kept in code is an anchor saying where in the text
to look.

This is not tidiness. If the number lived in code as well as in the rules, then
an amendment would leave the two disagreeing, and the code would keep deciding
confidently on the old threshold. Being confidently wrong is the worst failure
this pipeline can have.

The project's principles apply directly:

- Extraction is a regex anchor plus `app.ai.normalization`. No model is involved.
- **A failed extraction never falls back to an older number.** The rule is
  reported as UNDETERMINED instead. Withholding a judgment beats issuing one with
  no source behind it.
- `recorded` is a tripwire only and is never used to decide anything. When the
  extracted value differs from it, the rules have most likely been amended and
  the run says so.
"""

from __future__ import annotations

import re
from typing import Any

from ...normalization import extract_values
from .index import find_clause


# anchor  : regex selecting the *short span* of rule text holding the figure.
#           Group 1 is that span, and only it is handed to the normalizer.
#           Passing the whole clause would pick up unrelated numbers from the
#           same article (제21조, 100분의 50 …), so anchors stay narrow.
# unit    : the unit this rule compares in; only values in it are accepted.
# recorded: the value at the time this spec was written (2026-04-30 예규 제149호).
#           Tripwire only.
# note    : which sentence the figure lives in, so a person knows where to look
#           when an anchor stops matching.
SPECS: dict[str, dict[str, Any]] = {
    "warranty_period": {
        "source": "용역계약일반조건",
        "clause_no": "58조",
        "ref": "용역계약일반조건 제58조제1항",
        "desc_template": "인수 확인 후 {value}",
        "anchor": r"종료를\s*확인한\s*후\s*([^(]{1,12}?)간",
        "unit": "MONTH",
        "recorded": 12,
        "note": "제58조제1항 '사업의 종료를 확인한 후 1년간 ... 보수책임'",
    },
    "warranty_bond_rate": {
        "source": "용역계약일반조건",
        "clause_no": "59조",
        "ref": "용역계약일반조건 제59조제1항",
        "desc_template": "계약금액의 {value}",
        "anchor": r"하자보수보증금율\s*\(\s*([^,)]{1,20})",
        "unit": "PERCENT",
        "recorded": 2,
        "note": "제59조제1항 '하자보수보증금율(100분의 2, ...)'",
    },
    "penalty_cap": {
        "source": "용역계약일반조건",
        "clause_no": "18조",
        "ref": "용역계약일반조건 제18조제1항",
        "desc_template": "지체상금 총액은 계약금액의 {value} 이내",
        "anchor": r"초과하는\s*경우에는\s*([^으]{1,15}?)으로\s*한다",
        "unit": "PERCENT",
        "recorded": 30,
        "note": "제18조제1항 단서 '100분의 30을 초과하는 경우에는 100분의 30으로 한다'",
    },
    "inspection_period": {
        "source": "용역계약일반조건",
        "clause_no": "20조",
        "ref": "용역계약일반조건 제20조제2항",
        "desc_template": "통지받은 날부터 {value} 이내 검사",
        "anchor": r"통지를\s*받은\s*날부터\s*([^,]{1,12}?)\s*이내",
        "unit": "MONTH",
        "recorded": 14 / 30,
        "note": "제20조제2항 '통지를 받은 날부터 14일 이내에 ... 검사'",
    },
    "termination_threshold": {
        "source": "용역계약일반조건",
        "clause_no": "31조",
        "ref": "용역계약일반조건 제31조제1항",
        "desc_template": "계약금액 {value} 이상 감소 시 해제·해지 가능",
        "anchor": r"계약금액이\s*(.{1,15}?)\s*이상\s*감소",
        "unit": "PERCENT",
        "recorded": 40,
        "note": "제31조제1항제1호 '계약금액이 100분의 40이상 감소되었을 때'",
    },
    # A wording rule: there is no figure to compare. All that is checked is that
    # the standard wording is still in the rule text, so that an amendment
    # removing the joint-ownership principle does not go unnoticed.
    "ip_ownership": {
        "source": "용역계약일반조건",
        "clause_no": "56조",
        "ref": "용역계약일반조건 제56조제1항",
        "desc_template": "발주기관·계약상대자 공동소유, 지분 균등",
        "anchor": r"(공동으로\s*소유하며[^.]{0,40}지분은\s*균등)",
        "unit": None,
        "recorded": None,
        "note": "제56조제1항 '발주기관과 계약상대자가 공동으로 소유하며 ... 지분은 균등'",
    },
}

ResolveStatus = str  # "ok" | "clause_missing" | "anchor_failed" | "normalize_failed"


def format_value(value: float, unit: str | None) -> str:
    """Render a figure the way the rules phrase it, for display in a report."""
    if unit == "MONTH":
        if abs(value - round(value)) < 1e-6:
            months = int(round(value))
            if months % 12 == 0 and months >= 12:
                return f"{months // 12}년"
            return f"{months}개월"
        return f"{round(value * 30)}일"
    if unit == "PERCENT":
        return f"100분의 {value:g}"
    return str(value)


def resolve_standard_value(
    rule_id: str, clauses: list[dict[str, Any]]
) -> dict[str, Any]:
    """Extract one rule's threshold from the rule text.

    Returns `status` "ok" only when a usable value was actually read. Every other
    status leaves `value` at None, and the caller must not judge on it.
    """
    spec = SPECS[rule_id]
    clause = find_clause(clauses, spec["source"], spec["clause_no"])
    resolved: dict[str, Any] = {
        "rule_id": rule_id,
        "status": "clause_missing",
        "value": None,
        "unit": spec["unit"],
        "ref": spec["ref"],
        "desc": spec["desc_template"].replace("{value}", "?"),
        "raw": None,
        "clause": clause,
        "drift": None,
        "notes": "",
    }

    if clause is None:
        resolved["notes"] = (
            f"{spec['source']} {spec['clause_no']}를 표준 조문 인덱스에서 찾지 못함 "
            f"— 원본 예규 파일과 인덱스를 확인하세요"
        )
        return resolved

    match = re.search(spec["anchor"], clause["text"])
    if not match:
        resolved["status"] = "anchor_failed"
        resolved["notes"] = (
            f"예규 원문에서 표준값 위치를 찾지 못함(문언 개정 의심) — {spec['note']}"
        )
        return resolved

    raw = match.group(1).strip()
    resolved["raw"] = raw

    # Wording rule: confirming the standard sentence is still present is enough.
    if spec["unit"] is None:
        resolved["status"] = "ok"
        resolved["desc"] = spec["desc_template"]
        return resolved

    candidates = [
        value
        for value in extract_values(raw)
        if value["unit"] == spec["unit"] and value.get("value") is not None
    ]
    if not candidates:
        resolved["status"] = "normalize_failed"
        resolved["notes"] = f"표준값 구간 '{raw}'을 {spec['unit']} 단위로 정규화하지 못함"
        return resolved

    value = candidates[0]["value"]
    resolved["status"] = "ok"
    resolved["value"] = value
    resolved["desc"] = spec["desc_template"].format(
        value=format_value(value, spec["unit"])
    )

    recorded = spec.get("recorded")
    if recorded is not None and abs(value - recorded) > 1e-4:
        resolved["drift"] = {"recorded": recorded, "extracted": value}
        resolved["notes"] = (
            f"예규 원문 값({format_value(value, spec['unit'])})이 코드에 기록된 값"
            f"({format_value(recorded, spec['unit'])})과 다릅니다 — 예규 개정으로 보입니다. "
            f"원문 값으로 판정했습니다. values.py의 recorded를 갱신하세요."
        )
    return resolved


def resolve_all(clauses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resolve every rule's threshold at once."""
    return {rule_id: resolve_standard_value(rule_id, clauses) for rule_id in SPECS}
