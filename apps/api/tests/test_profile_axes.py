"""프로필 축 — 같은 공고에 다른 회사를 대면 판정이 갈리는지 고정한다.

골든셋 v0.2 는 회사 프로필이 거의 한 종류다(규모 SMALL 31/32, 인증 보유 4건, 실적 보유
10건, extensions 전부 비어 있음). 그래서 비교 코드를 **비교할 거리가 없는 입력**으로
테스트하게 된다. 실제로 판정 코드에 결함을 심어 보면, 문자열 매칭을 느슨하게 하든 완전
일치로만 하든 v0.2 의 점수는 한 자리도 안 바뀐다.

여기 넷은 v0.2 의 실제 요건을 그대로 쓰고 회사만 바꾼 것이다. 고정하는 성질은 다투지 않는
것들이다 — 경상남도는 경상북도가 아니고, 전주시는 전북특별자치도 안이고, 품목이 다른
직접생산확인증명서는 그 품목의 증명이 아니고, 11년 전 실적은 최근 3년 실적이 아니다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.qualification.rules.clause_safety import unsafe_clause_reason
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot
from apps.api.app.qualification.rules.judgment import judge_requirement


AXES_PATH = (
    Path(__file__).resolve().parents[3]
    / "samples" / "golden" / "profile-axes-v0.1" / "cases.json"
)


def _cases() -> list[dict]:
    return json.loads(AXES_PATH.read_text(encoding="utf-8"))["cases"]


def _ids(cases: list[dict]) -> list[str]:
    return [f"{case['case_id']}-{case['axis']}" for case in cases]


CASES = _cases()


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_each_axis_judges_to_its_expected_status(case: dict) -> None:
    item = case["canonical_inputs"][0]
    requirement = QualificationRequirement.model_validate(item["requirement"])
    profile = CompanyProfileSnapshot.model_validate(case["profile"])

    judgment = judge_requirement(
        requirement,
        profile,
        preflight_case_id=case["case_id"],
        reference_date=date.fromisoformat(case["reference_date"]),
    )

    assert judgment.status == item["semantic_expected"], case["why"]


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_each_axis_requirement_actually_reaches_the_judge(case: dict) -> None:
    """가드에 걸리는 요건에 회사를 대봐야 판정 코드는 한 줄도 돌지 않는다.

    v0.2 는 104행 중 34행이 안전 가드나 composite 로 판정 전에 멈춘다 —
    PERFORMANCE_COUNT 는 7행 전부. 축을 그런 요건에 붙이면 무엇을 바꿔도 UNKNOWN 이라
    아무것도 검증되지 않는다. 실제로 A4 를 처음에 그런 요건에 붙였다가 걸렸다.
    """
    requirement = case["canonical_inputs"][0]["requirement"]

    assert unsafe_clause_reason(requirement.get("raw") or "") is None
    assert requirement.get("condition_complexity") != "composite"


def test_the_axes_reuse_frozen_requirements_instead_of_inventing_them() -> None:
    """요건을 지어내면 "우리 코드가 답하기 좋은 공고" 를 만들게 된다.

    축은 회사만 바꾼다. 요건은 고정본에서 그대로 가져오고, 어느 케이스에서 왔는지 남긴다.
    """
    frozen = json.loads(
        (AXES_PATH.parent.parent / "qualification-v0.2" / "fixture_bundle.json")
        .read_text(encoding="utf-8")
    )
    frozen_raws = {
        (item["requirement"]["type"], item["requirement"].get("raw"))
        for case in frozen["cases"]
        for item in case["canonical_inputs"]
    }

    for case in CASES:
        requirement = case["canonical_inputs"][0]["requirement"]
        assert case["derived_from"], case["case_id"]
        assert (requirement["type"], requirement.get("raw")) in frozen_raws, case["case_id"]


def test_every_axis_uses_a_distinct_profile_shape() -> None:
    """네 축이 같은 회사면 축이 하나인 것과 같다."""
    shapes = {
        json.dumps(case["profile"], ensure_ascii=False, sort_keys=True) for case in CASES
    }

    assert len(shapes) == len(CASES)
