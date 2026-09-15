"""Adapter from source-grounded extraction slots to canonical requirements.

The extraction layer keeps human-readable Korean slot types as an internal
interface. Production maps those slots into the closed eight-type canonical
taxonomy. Unsupported or incomplete slots become diagnostics rather than being
forced into a judgment-ready requirement.
"""

from __future__ import annotations

import re
from typing import Any

from ...contracts import QualificationRequirement, RequirementOperator, RequirementType
from ....qualification.rules.clause_safety import unsafe_clause_reason
from .deduplicate import _INDUSTRY_NAME_VALUE_RE, _REGISTRATION_ACT_VALUE_RE

_COUNT_RE = re.compile(r"(\d+)\s*(?:건|회)\s*(이상|초과|이하|미만)?")
_INDUSTRY_CODE_RE = re.compile(r"업종\s*코드\s*[:：]?\s*([0-9]{4}(?:\s*[,/·]\s*[0-9]{4})*)(?![0-9])")
_SIZE_EXCLUSION_RE = re.compile(
    r"참여\s*(?:제한|불가|배제|금지)"
    r"|참가\s*(?:제한|불가|배제)"
    r"|참여할\s*수\s*없"
    r"|참여\s*(?:를)?\s*(?:제외|배제)"
    r"|입찰\s*참가\s*자격\s*(?:을)?\s*제한"
)


# 닫힌 식별자 — 사람이 달리 쓸 수 없는 값. 업종코드 4자리, 세부품명번호 10자리.
# 모델이 유형을 뭐라고 붙이든 이 숫자는 원문에 그대로 있다.
_PRODUCT_CODE_RE = re.compile(r"(?<![0-9])([0-9]{10})(?![0-9])")
_REGISTRATION_CONTEXT_RE = re.compile(r"등록|신고|영업|허가|면허")
_PRODUCT_CONTEXT_RE = re.compile(r"직접\s*생산\s*확인|세부\s*품명|품명\s*번호")


# "A(1257) 또는 B(6770) 또는 C(6786) 등록업체" — 안전 가드는 이것을 막는다. 하나로
# 줄일 수 없는 조건을 충족/미충족으로 단정하면 안 되기 때문이다. 옳은 판단이지만,
# **ANY_OF 가 바로 그 '또는' 의 안전한 표현**이다. 줄이지 않고 관계를 그대로 담을 수
# 있으면 막을 이유가 없다. 그래서 이 모양 하나만 좁게 연다.
#
# 조건을 좁게 두는 이유는 '또는' 이 늘 대등한 선택지는 아니기 때문이다 — "A 또는
# B 기준을 충족한 업체" 처럼 뒤쪽이 예외·완화 조항이면 ANY_OF 가 아니다. 그래서
# 갈라진 조각이 **전부 업종명(업종코드) 하나씩** 일 때만 인정한다.
_ALTERNATION_SPLIT_RE = re.compile(r"\s*또는\s*")
_EXCEPTION_WORDS_RE = re.compile(
    r"다만|단서|예외|제외|불구하고|각\s*호|아니(?:어야|하여야|한)|해당되지|경우에\s*한"
)
_NAMED_INDUSTRY_CODE_RE = re.compile(r"[가-힣A-Za-z·ㆍ\s]{2,}?업\s*\(\s*([0-9]{4})\s*\)")


def industry_code_alternation(raw: str) -> list[str] | None:
    """'또는' 으로 갈린 조각이 전부 업종명(코드) 하나씩이면 그 코드 목록. 아니면 None."""
    if _EXCEPTION_WORDS_RE.search(raw):
        return None
    parts = _ALTERNATION_SPLIT_RE.split(raw)
    if len(parts) < 2:
        return None
    codes: list[str] = []
    for part in parts:
        found = _NAMED_INDUSTRY_CODE_RE.findall(part)
        if len(found) != 1:
            return None
        codes.append(found[0])
    if len(set(codes)) != len(codes):
        return None
    return codes


def salvage_closed_identifier(raw: str) -> tuple[RequirementType, str] | None:
    """분류가 '기타요건' 으로 와도 원문의 닫힌 식별자로 유형을 되살린다.

    되살리는 기준을 좁게 둔다 — 식별자가 **정확히 하나**이고, 그것이 등록·신고 맥락에
    쓰였을 때만. 여러 개면 AND/OR 관계를 모르므로 살리지 않는다(이미 업종요건 경로가
    같은 이유로 멈춘다). 숫자가 아닌 표현은 건드리지 않는다 — 지역명·인증명처럼 사람이
    달리 쓸 수 있는 값을 여기서 추측하기 시작하면 틀린 확정으로 간다.
    """
    industry_codes = {
        code
        for group in _INDUSTRY_CODE_RE.findall(raw)
        for code in re.findall(r"[0-9]{4}", group)
    }
    if len(industry_codes) == 1 and _REGISTRATION_CONTEXT_RE.search(raw):
        return "INDUSTRY", next(iter(industry_codes))

    product_codes = set(_PRODUCT_CODE_RE.findall(raw))
    if len(product_codes) == 1 and _PRODUCT_CONTEXT_RE.search(raw):
        return "REGISTRATION_CERTIFICATION", next(iter(product_codes))

    return None


def _squash_name(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _op(word: str | None) -> RequirementOperator | None:
    return {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}.get(word)  # type: ignore[return-value]


def _performance_scope(slot: dict[str, Any], *, aggregation: str | None = None) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    if aggregation is not None:
        scope["aggregation"] = aggregation
    client_requirement = (slot.get("실적기관_raw") or "").strip()
    if client_requirement:
        scope["client_requirement"] = client_requirement
    experience_field = (slot.get("경험분야_raw") or "").strip()
    if experience_field:
        scope["experience_field"] = experience_field
    return scope


def adapt_legacy_slot(
    slot: dict[str, Any],
    *,
    notice_version_id: str,
    key_prefix: str,
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """Map one validated extraction slot into zero or more canonical requirements."""
    slot_type = slot.get("유형")
    raw = (slot.get("raw") or "").strip()
    unsafe_reason = unsafe_clause_reason(raw)
    alternation = (
        industry_code_alternation(raw)
        if unsafe_reason == "ALTERNATIVE_OR_EXCEPTION_RULE"
        else None
    )
    if unsafe_reason and alternation is None:
        return [], [{"code": "UNMAPPED_REQUIREMENT", "raw": raw, "reason": unsafe_reason}]
    diagnostics: list[dict[str, Any]] = []
    requirements: list[QualificationRequirement] = []
    group_key = f"{key_prefix}-GROUP"

    # Only a single explicit code can replace an industry/registration name.
    # Multiple codes need their AND/OR relationship resolved before mapping.
    industry_codes = {
        code for group in _INDUSTRY_CODE_RE.findall(raw)
        for code in re.findall(r"[0-9]{4}", group)
    }
    if not industry_codes:
        # "업종코드 : 1450" 뿐 아니라 "폐기물수집·운반업(1227)" 처럼 업종명 뒤 괄호에
        # 바로 적는 공고가 많다. 업종명이 앞에 붙어 있을 때만 읽는다 — 그냥 네 자리
        # 숫자를 코드로 보면 연도·금액을 업종으로 만든다.
        named = set(_NAMED_INDUSTRY_CODE_RE.findall(raw))
        if len(named) == 1:
            industry_codes = named
    if slot_type in {"업종요건", "등록요건"} and len(industry_codes) > 1 and alternation is None:
        return [], [{"code": "UNMAPPED_INDUSTRY", "raw": raw, "reason": "복수 업종코드의 관계를 확인해야 합니다."}]

    def add(
        suffix: str,
        req_type: RequirementType,
        *,
        operator: RequirementOperator | None = None,
        value: int | float | str | None = None,
        unit: str | None = None,
        period_months: float | None = None,
        scope: dict[str, Any] | None = None,
        group_operator: RequirementOperator | str = "ALL_OF",
    ) -> None:
        requirements.append(
            QualificationRequirement(
                requirement_key=f"{key_prefix}-{suffix}",
                requirement_group_key=group_key,
                group_operator=group_operator,
                notice_version_id=notice_version_id,
                type=req_type,
                operator=operator,
                value=value,
                unit=unit,
                period_months=period_months,
                scope=scope or {},
                raw=raw,
            )
        )

    if alternation is not None:
        # 관계를 줄이지 않고 그대로 담는다 — 코드 하나가 요건 하나, 묶음은 ANY_OF.
        # 판정기는 이 묶음을 "하나라도 충족하면 충족" 으로 읽는다. 안전 가드가 막던
        # 이유(하나로 줄일 수 없다)가 사라지므로 막을 이유도 사라진다.
        for index, code in enumerate(alternation, start=1):
            add(f"INDUSTRY-{index}", "INDUSTRY", operator="MATCH", value=code,
                group_operator="ANY_OF")
        diagnostics.append({
            "code": "INDUSTRY_ALTERNATION",
            "raw": raw,
            "codes": list(alternation),
        })
        return requirements, diagnostics

    if slot_type == "실적요건":
        amount = slot.get("금액_norm") or {}
        period = slot.get("기간_norm") or {}
        period_months = period.get("value") if period.get("parse_status") == "success" else None
        if slot.get("기간_raw") and period_months is None:
            return [], [{"code": "UNMAPPED_PERFORMANCE", "raw": raw, "reason": "기간을 안전하게 정규화하지 못했습니다."}]
        aggregation = "SUM" if re.search(r"합계|합산|누적|총액", raw) else "UNSPECIFIED"

        if amount.get("parse_status") == "success":
            if amount.get("value") is not None:
                add(
                    "AMOUNT",
                    "PERFORMANCE_AMOUNT",
                    operator=amount.get("op"),
                    value=amount.get("value"),
                    unit=amount.get("unit") or "KRW",
                    period_months=period_months,
                    scope=_performance_scope(slot, aggregation=aggregation),
                )
            elif amount.get("range"):
                amount_range = dict(amount["range"])
                add(
                    "AMOUNT",
                    "PERFORMANCE_AMOUNT",
                    operator="RANGE",
                    unit=amount.get("unit") or "KRW",
                    period_months=period_months,
                    scope={
                        **_performance_scope(slot, aggregation=aggregation),
                        "min": amount_range.get("min"),
                        "min_operator": amount_range.get("min_op"),
                        "max": amount_range.get("max"),
                        "max_operator": amount_range.get("max_op"),
                    },
                )

        count_source = (slot.get("건수_raw") or raw).strip()
        count_match = _COUNT_RE.search(count_source)
        if count_match:
            add(
                "COUNT",
                "PERFORMANCE_COUNT",
                operator=_op(count_match.group(2)) or ">=",
                value=int(count_match.group(1)),
                unit="COUNT",
                period_months=period_months,
                scope=_performance_scope(slot),
            )

        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add(
                "EXPERIENCE",
                "EXPERIENCE_FIELD",
                operator="MATCH",
                value=experience_field,
                period_months=period_months,
                scope={"source": "PERFORMANCE", **_performance_scope(slot)},
            )

        if not requirements:
            diagnostics.append({"code": "UNMAPPED_PERFORMANCE", "raw": raw})

    elif slot_type == "경험분야요건":
        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add("EXPERIENCE", "EXPERIENCE_FIELD", operator="MATCH", value=experience_field)
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
            add(
                "STAFF",
                "STAFF",
                operator=headcount.get("op") or ">=",
                value=headcount.get("value"),
                unit=headcount.get("unit") or "PERSON",
                scope={"role": role} if role else {},
            )
        elif role:
            add("STAFF", "STAFF", operator="MATCH", value=role, scope={"role": role})
        else:
            diagnostics.append({"code": "UNMAPPED_STAFF", "raw": raw})

    elif slot_type in {"인증요건", "면허요건", "등록요건"}:
        name = (slot.get("등록인증_raw") or "").strip()
        issuer = (slot.get("발급기관_raw") or "").strip()
        kind = {
            "인증요건": "CERTIFICATION",
            "면허요건": "LICENSE",
            "등록요건": "REGISTRATION",
        }[slot_type]
        # [재현 2026-09-15] 등록요건뿐 아니라 인증·면허로 분류돼도 원문에 업종코드가 하나
        # 있으면 업종 요건일 수 있다. 실측에서 같은 "영업신고(업종코드 : 1450)" 조항을 모델이
        # 인증요건으로 낸 실행이 있었고, 그때 INDUSTRY 1450 이 아예 안 만들어져 인증 쪽에서
        # 미달이 났다.
        #
        # 단, **값이 업종명이나 등록 행위 모양일 때만**이다. "업종코드: 1468 업체는 ISO 27001
        # 인증 보유" 처럼 같은 조항에 진짜 인증이 적혀 있으면 그 인증은 별개 요건이다 —
        # 코드가 있다고 그것을 업종으로 바꾸면 ISO 27001 을 삼킨다(test_canonicalize 가 막는다).
        looks_like_industry = bool(name) and (
            _INDUSTRY_NAME_VALUE_RE.fullmatch(_squash_name(name))
            or _REGISTRATION_ACT_VALUE_RE.fullmatch(_squash_name(name))
        )
        if industry_codes and (slot_type == "등록요건" or looks_like_industry):
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)), scope={"kind": kind, "industry_name": name})
        elif name:
            scope: dict[str, Any] = {"kind": kind}
            if issuer:
                scope["issuer"] = issuer
            add(
                "CERT",
                "REGISTRATION_CERTIFICATION",
                operator="MATCH",
                value=name,
                scope=scope,
            )
        else:
            diagnostics.append({"code": "UNMAPPED_REGISTRATION_CERTIFICATION", "raw": raw})

    elif slot_type == "기업규모요건":
        company_size = (slot.get("기업규모_raw") or "").strip()
        if company_size:
            add(
                "COMPANY_SIZE",
                "COMPANY_SIZE",
                operator="MATCH",
                value=company_size,
                scope={"restriction": "EXCLUDE"}
                if _SIZE_EXCLUSION_RE.search(raw)
                else {},
            )
        else:
            diagnostics.append({"code": "UNMAPPED_COMPANY_SIZE", "raw": raw})

    elif slot_type == "기타요건":
        # [재현 2026-09-14] '기타요건' 은 통째로 버려졌다. 그런데 모델은 업종코드가 박힌
        # 조항을 '기타요건' 으로 분류하는 일이 잦다 — 구내식당 공고의 "영업신고(업종코드 :
        # 1450)를 하여 집단급식소 영업이 가능한 법인사업자" 가 그랬고, 골든셋은 이것을
        # INDUSTRY 1450 으로 본다. 분류는 실행마다 흔들려도 **원문의 숫자는 흔들리지 않는다.**
        # 그래서 코드가 직접 읽어 살린다.
        salvaged = salvage_closed_identifier(raw)
        if salvaged is None:
            diagnostics.append({"code": "UNMAPPED_REQUIREMENT", "raw": raw})
        else:
            salvaged_type, salvaged_value = salvaged
            add(salvaged_type, salvaged_type, operator="MATCH", value=salvaged_value)
            diagnostics.append({
                "code": "SALVAGED_CLOSED_IDENTIFIER",
                "raw": raw,
                "salvaged_type": salvaged_type,
                "value": salvaged_value,
            })
    else:
        diagnostics.append({"code": "UNKNOWN_LEGACY_TYPE", "type": slot_type, "raw": raw})

    return requirements, diagnostics
