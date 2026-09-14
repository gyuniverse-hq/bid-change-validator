"""같은 조항이 두 유형으로 분류됐을 때 자격 있는 회사를 떨어뜨리지 않는지.

[재현 2026-09-14] 모델의 유형 분류는 실행마다 흔들린다. 구내식당 공고의 한 조항이
어떤 실행에서는 INDUSTRY, 어떤 실행에서는 REGISTRATION_CERTIFICATION, 어떤 실행에서는
**둘 다** 로 나왔다. 둘 다 나온 실행이 위험하다 — ALL_OF 묶음이라 둘 다 충족해야 하는데,
업종 1450 을 실제로 보유한 회사가 인증 쪽에서 미달을 받는다.

여기서 고정하는 것은 두 가지다. 접어야 할 것을 접는가, 그리고 **접으면 안 되는 것을
그대로 두는가.** 뒤엣것이 더 중요하다 — 잘못 접으면 진짜 요건이 사라지고, 그건 조용히
지나간다. 첫 구현에서 실제로 ISO 9001 을 삼켰다.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.ai.qualification.canonical.deduplicate import deduplicate_requirements
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot
from apps.api.app.qualification.rules.judgment import judge_requirement


LONG_RAW = (
    "나. 식품위생법에 의거 단체급식업 등록업체로서 결격사유가 없는 업체 "
    "식품위생법에 따른 인·허가를 득하고 영업신고(업종코드 : 1450)를 한 업체"
)
SHORT_RAW = "나. 식품위생법에 의거 단체급식업 등록업체로서 결격사유가 없는 업체"


def _requirement(key: str, type_: str, value: str, raw: str) -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key=key,
        notice_version_id="NV-1",
        type=type_,
        operator="MATCH",
        value=value,
        raw=raw,
        requirement_group_key="G",
        group_operator="ALL_OF",
    )


def test_the_same_fact_classified_twice_is_folded_onto_the_industry_code() -> None:
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", "단체급식업등록", SHORT_RAW),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert [(item.type, item.value) for item in kept] == [("INDUSTRY", "1450")]
    assert [item["code"] for item in diagnostics] == ["MERGED_INDUSTRY_REGISTRATION"]
    # 무엇이 접혔는지 남는다 — 담당자가 확인할 수 있어야 한다.
    assert diagnostics[0]["dropped_value"] == "단체급식업등록"
    assert diagnostics[0]["kept_value"] == "1450"


def test_folding_prevents_a_wrong_unsatisfied() -> None:
    """이 정리가 무엇을 막는지 판정까지 내려가서 확인한다."""
    profile = CompanyProfileSnapshot.model_validate({
        "company_id": "C-1",
        "industries": [{"code": "1450", "name": "단체급식업", "verified": False}],
        "certifications": [],
        "completeness": {
            "certifications": True, "company_size": True, "industries": True,
            "performances": True, "region": True, "staff_roles": True, "staff_total": True,
        },
    })
    registration = _requirement(
        "A", "REGISTRATION_CERTIFICATION", "단체급식업등록", SHORT_RAW
    )

    # 정리 전에는 업종을 보유한 회사가 인증 쪽에서 미달을 받았다.
    before = judge_requirement(
        registration, profile, preflight_case_id="X", reference_date=date(2026, 9, 14)
    )
    assert before.status == "UNSATISFIED"

    kept, _ = deduplicate_requirements([
        registration, _requirement("B", "INDUSTRY", "1450", LONG_RAW)
    ])
    statuses = {
        judge_requirement(
            item, profile, preflight_case_id="X", reference_date=date(2026, 9, 14)
        ).status
        for item in kept
    }

    assert statuses == {"SATISFIED"}


def test_exact_duplicates_collapse_to_one() -> None:
    """실측 run 에서 같은 INDUSTRY 1450 이 세 번 들어왔다. 개수가 부풀어 보인다."""
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "INDUSTRY", "1450", LONG_RAW),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
        _requirement("C", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert len(kept) == 1
    assert [item["code"] for item in diagnostics] == [
        "DUPLICATE_REQUIREMENT", "DUPLICATE_REQUIREMENT"
    ]


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("ISO 9001", "규격 이름은 업종명이 아니다 — 별개 인증 요건"),
        ("직접생산확인증명서", "업종명이 아니다"),
        ("KS Q 27001", "로마자·숫자가 섞이면 규격 이름"),
    ],
)
def test_a_real_certification_requirement_is_never_folded(value: str, why: str) -> None:
    raw = f"업종(1257) 등록 및 {value} 보유 업체"
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", value, raw),
        _requirement("B", "INDUSTRY", "1257", raw),
    ])

    assert len(kept) == 2, why
    assert diagnostics == []


def test_two_different_requirements_in_one_clause_are_left_alone() -> None:
    """한 조항이 지역과 업종을 정말로 둘 다 요구할 수 있다. 접으면 판정이 사라진다."""
    raw = "소재지가 전북특별자치도이고 업종(1257)을 등록한 업체"
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "REGION", "전북특별자치도", raw),
        _requirement("B", "INDUSTRY", "1257", raw),
    ])

    assert len(kept) == 2
    assert diagnostics == []


def test_nothing_is_folded_onto_an_industry_without_a_code() -> None:
    """접는 근거는 '코드가 더 확실하다' 이다. 코드가 없으면 근거가 없다."""
    kept, _ = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", "단체급식업등록", SHORT_RAW),
        _requirement("B", "INDUSTRY", "단체급식업", LONG_RAW),
    ])

    assert len(kept) == 2


def test_an_unrelated_clause_is_not_folded_even_with_a_matching_name() -> None:
    """원문이 겹치지 않으면 같은 조항이 아니다."""
    kept, _ = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", "단체급식업등록", "다. 별개 조항의 단체급식업등록 요구"),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert len(kept) == 2
