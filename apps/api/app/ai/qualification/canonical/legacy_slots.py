"""Map source-grounded slots to canonical requirements without losing unresolved constraints."""
from __future__ import annotations
import re
from typing import Any
from ...contracts import QualificationRequirement, RequirementOperator, RequirementType
from ....qualification.rules.clause_safety import unsafe_clause_reason
from .slot_money import money_normalization_error
from .industry_binding import registration_alias_code
from .procedure import procedure_mentions, is_procedure_name, procedure_diagnostic

_COUNT_RE = re.compile(r"(\d+)\s*(?:건|회)\s*(이상|초과|이하|미만)?")
_INDUSTRY_CODE_RE = re.compile(r"업종\s*코드\s*[:：]?\s*([0-9]{4}(?:\s*[,/·]\s*[0-9]{4})*)(?![0-9])")
_SIZE_EXCLUSION_RE = re.compile(r"참여\s*(?:제한|불가|배제|금지)|참가\s*(?:제한|불가|배제)|참여할\s*수\s*없"
    r"|참여\s*(?:를)?\s*(?:제외|배제)|입찰\s*참가\s*자격\s*(?:을)?\s*제한")


def _op(word: str | None) -> RequirementOperator | None:
    return {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}.get(word)


def _performance_scope(slot: dict[str, Any], *, aggregation: str | None = None) -> dict[str, Any]:
    scope = {}
    if aggregation is not None:
        scope["aggregation"] = aggregation
    for source, target in (("실적기관_raw", "client_requirement"), ("경험분야_raw", "experience_field")):
        value = (slot.get(source) or "").strip()
        if value:
            scope[target] = value
    return scope


def adapt_legacy_slot(slot: dict[str, Any], *, notice_version_id: str, key_prefix: str,
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    slot_type = slot.get("유형")
    raw = (slot.get("raw") or "").strip()
    registration_name = str(slot.get("등록인증_raw") or "")
    mentions = procedure_mentions(raw, registration_name)
    diagnostics = [procedure_diagnostic(raw, mentions)] if mentions else []
    unsafe_reason = unsafe_clause_reason(raw)
    if unsafe_reason:
        return [], diagnostics + [{"code": "UNMAPPED_REQUIREMENT", "raw": raw, "reason": unsafe_reason}]
    requirements = []
    group_key = f"{key_prefix}-GROUP"
    industry_codes = {code for group in _INDUSTRY_CODE_RE.findall(raw) for code in re.findall(r"[0-9]{4}", group)}
    if slot_type in {"업종요건", "등록요건"} and len(industry_codes) > 1:
        return [], diagnostics + [{"code": "UNMAPPED_INDUSTRY", "raw": raw, "reason": "복수 업종코드의 관계를 확인해야 합니다."}]

    def add(suffix: str, req_type: RequirementType, *, operator: RequirementOperator | None = None,
            value: int | float | str | None = None, unit: str | None = None,
            period_months: float | None = None, scope: dict[str, Any] | None = None) -> None:
        requirements.append(QualificationRequirement(requirement_key=f"{key_prefix}-{suffix}",
            requirement_group_key=group_key, group_operator="ALL_OF", notice_version_id=notice_version_id,
            type=req_type, operator=operator, value=value, unit=unit, period_months=period_months, scope=scope or {}, raw=raw))

    if slot_type == "실적요건":
        amount = slot.get("금액_norm") or {}
        if amount or slot.get("금액_raw"):
            error = money_normalization_error(amount, slot.get("금액_raw"))
            if error:
                # 금액 일부를 버리고 나머지 조건만 확정하면 복합조건이 약해진다.
                return [], diagnostics + [{"code": "UNMAPPED_PERFORMANCE", "raw": raw, "reason": error,
                    "detail_field": "금액_raw", "detail_value": slot.get("금액_raw"),
                    "observed_unit": amount.get("unit") if isinstance(amount, dict) else None}]
        period = slot.get("기간_norm") or {}
        months = period.get("value") if period.get("parse_status") == "success" else None
        if slot.get("기간_raw") and months is None:
            return [], diagnostics + [{"code": "UNMAPPED_PERFORMANCE", "raw": raw, "reason": "기간을 안전하게 정규화하지 못했습니다."}]
        aggregation = "SUM" if re.search(r"합계|합산|누적|총액", raw) else "UNSPECIFIED"
        if amount.get("parse_status") == "success":
            if amount.get("value") is not None:
                add("AMOUNT", "PERFORMANCE_AMOUNT", operator=amount.get("op"), value=amount.get("value"),
                    unit=amount.get("unit") or "KRW", period_months=months, scope=_performance_scope(slot, aggregation=aggregation))
            elif amount.get("range"):
                bounds = dict(amount["range"])
                add("AMOUNT", "PERFORMANCE_AMOUNT", operator="RANGE", unit=amount.get("unit") or "KRW",
                    period_months=months, scope={**_performance_scope(slot, aggregation=aggregation),
                        "min": bounds.get("min"), "min_operator": bounds.get("min_op"),
                        "max": bounds.get("max"), "max_operator": bounds.get("max_op")})
        match = _COUNT_RE.search((slot.get("건수_raw") or raw).strip())
        if match:
            add("COUNT", "PERFORMANCE_COUNT", operator=_op(match.group(2)) or ">=", value=int(match.group(1)),
                unit="COUNT", period_months=months, scope=_performance_scope(slot))
        field = (slot.get("경험분야_raw") or "").strip()
        if field:
            add("EXPERIENCE", "EXPERIENCE_FIELD", operator="MATCH", value=field, period_months=months,
                scope={"source": "PERFORMANCE", **_performance_scope(slot)})
        if not requirements:
            diagnostics.append({"code": "UNMAPPED_PERFORMANCE", "raw": raw})
    elif slot_type == "경험분야요건":
        field = (slot.get("경험분야_raw") or "").strip()
        if field:
            add("EXPERIENCE", "EXPERIENCE_FIELD", operator="MATCH", value=field)
        else:
            diagnostics.append({"code": "UNMAPPED_EXPERIENCE_FIELD", "raw": raw})
    elif slot_type == "업종요건":
        industry = (slot.get("업종_raw") or "").strip()
        if industry_codes:
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)), scope={"industry_name": industry} if industry else {})
        elif industry:
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=industry)
        else:
            diagnostics.append({"code": "UNMAPPED_INDUSTRY", "raw": raw})
    elif slot_type == "지역요건":
        region = (slot.get("지역_raw") or "").strip()
        if region:
            add("REGION", "REGION", operator="MATCH", value=region)
        else:
            diagnostics.append({"code": "UNMAPPED_REGION", "raw": raw})
    elif slot_type == "인력요건":
        headcount = slot.get("인원_norm") or {}
        role = (slot.get("인력역할_raw") or "").strip()
        if headcount.get("parse_status") == "success" and headcount.get("value") is not None:
            add("STAFF", "STAFF", operator=headcount.get("op") or ">=", value=headcount.get("value"),
                unit=headcount.get("unit") or "PERSON", scope={"role": role} if role else {})
        elif role:
            add("STAFF", "STAFF", operator="MATCH", value=role, scope={"role": role})
        else:
            diagnostics.append({"code": "UNMAPPED_STAFF", "raw": raw})
    elif slot_type in {"인증요건", "면허요건", "등록요건"}:
        name = (slot.get("등록인증_raw") or "").strip()
        issuer = (slot.get("발급기관_raw") or "").strip()
        kind = {"인증요건": "CERTIFICATION", "면허요건": "LICENSE", "등록요건": "REGISTRATION"}[slot_type]
        if is_procedure_name(name, raw):
            if len(industry_codes) == 1:
                add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)))
            elif len(industry_codes) > 1:
                diagnostics.append({"code": "UNMAPPED_INDUSTRY", "raw": raw,
                    "reason": "절차와 혼합된 복수 업종의 관계 확인이 필요합니다."})
        elif (slot_type == "등록요건" and industry_codes and not issuer
              and (not name or registration_alias_code(name, raw) == next(iter(industry_codes)))):
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)), scope={"kind": kind, "industry_name": name})
        elif name and not issuer and (bound_code := registration_alias_code(name, raw)):
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=bound_code, scope={"industry_name": name})
            diagnostics.append({"code": "INDUSTRY_ALIAS_RESOLVED", "raw": raw, "original_type": slot_type,
                "original_value": name, "code_value": bound_code})
        elif name:
            scope = {"kind": kind}
            if issuer:
                scope["issuer"] = issuer
            add("CERT", "REGISTRATION_CERTIFICATION", operator="MATCH", value=name, scope=scope)
        else:
            diagnostics.append({"code": "UNMAPPED_REGISTRATION_CERTIFICATION", "raw": raw})
    elif slot_type == "기업규모요건":
        size = (slot.get("기업규모_raw") or "").strip()
        if size:
            add("COMPANY_SIZE", "COMPANY_SIZE", operator="MATCH", value=size,
                scope={"restriction": "EXCLUDE"} if _SIZE_EXCLUSION_RE.search(raw) else {})
        else:
            diagnostics.append({"code": "UNMAPPED_COMPANY_SIZE", "raw": raw})
    elif slot_type == "기타요건":
        diagnostics.append({"code": "UNMAPPED_REQUIREMENT", "raw": raw})
    else:
        diagnostics.append({"code": "UNKNOWN_LEGACY_TYPE", "type": slot_type, "raw": raw})
    return requirements, diagnostics
