"""모델 분류가 흔들려도 원문의 숫자는 흔들리지 않는다.

[재현 2026-09-14] 구내식당 공고(R26BK01633750)를 여러 번 돌린 실측에서, 모델이
"영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자" 조항을 어떤
실행에서는 업종요건으로, 어떤 실행에서는 **기타요건**으로 분류했다. 기타요건은 통째로
버려졌다 — 골든셋은 이 조항을 INDUSTRY 1450 으로 본다.

분류는 작문이라 실행마다 달라진다. 업종코드 네 자리는 원문에 박혀 있어 달라지지 않는다.
그래서 분류가 '기타요건' 으로 와도 코드가 직접 읽어 살린다.

살리는 범위를 좁게 둔다. 숫자로 된 닫힌 식별자만 — 지역명·인증명처럼 사람이 달리 쓸 수
있는 값을 여기서 추측하기 시작하면 틀린 확정으로 간다.
"""

from __future__ import annotations

import pytest

from apps.api.app.ai.qualification.canonical.legacy_slots import adapt_legacy_slot
from apps.api.app.ai.qualification.canonical.legacy_slots import salvage_closed_identifier


def _adapt(raw: str, slot_type: str = "기타요건"):
    return adapt_legacy_slot(
        {"유형": slot_type, "raw": raw},
        notice_version_id="NV-1",
        key_prefix="REQ-001",
    )


def test_an_industry_code_survives_a_wrong_classification() -> None:
    raw = "식품위생법에 따른 인·허가를 득하고 영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자"

    requirements, diagnostics = _adapt(raw)

    assert [(item.type, item.value) for item in requirements] == [("INDUSTRY", "1450")]
    assert [item["code"] for item in diagnostics] == ["SALVAGED_CLOSED_IDENTIFIER"]
    # 원문은 그대로 달고 간다 — 판정 근거가 살린 값이 아니라 공고 문장이어야 한다.
    assert requirements[0].raw == raw


def test_a_product_code_survives_too() -> None:
    raw = "직접생산확인증명서[세부품명: 조형물(세부품명번호 10자리: 6012100201)] 보유 업체"

    requirements, _ = _adapt(raw)

    assert [(item.type, item.value) for item in requirements] == [
        ("REGISTRATION_CERTIFICATION", "6012100201")
    ]


def test_two_codes_are_not_salvaged() -> None:
    """둘 이상이면 AND 인지 OR 인지 모른다. 업종요건 경로가 멈추는 이유와 같다."""
    raw = "폐기물중간처분업(업종코드 : 1257) 또는 폐기물종합재활용업(업종코드 : 6786) 등록업체"

    requirements, diagnostics = _adapt(raw)

    assert requirements == []
    assert [item["code"] for item in diagnostics] == ["UNMAPPED_REQUIREMENT"]


@pytest.mark.parametrize(
    "raw",
    [
        "본점 소재지가 경상북도에 소재하고 있는 업체",          # 지역명은 추측하지 않는다
        "최근 3년 이내 유사 용역 실적 2건 이상 보유 업체",       # 숫자가 있어도 식별자가 아니다
        "입찰참가등록 및 입찰서 제출 정시에 마감합니다.",         # 요건이 아니다
        "사업자등록번호 1234567890 을 보유한 업체",             # 10자리지만 품명 맥락이 아니다
    ],
)
def test_prose_is_left_alone(raw: str) -> None:
    """넓히면 틀린 확정으로 간다. 살리는 것은 숫자로 된 닫힌 식별자뿐이다."""
    requirements, diagnostics = _adapt(raw)

    assert requirements == []
    assert [item["code"] for item in diagnostics] == ["UNMAPPED_REQUIREMENT"]


def test_an_unsafe_clause_is_still_not_salvaged() -> None:
    """안전 가드가 먼저다. 복합·예외 조항은 업종코드가 있어도 판정하지 않는다."""
    raw = (
        "건설폐기물수집·운반업(업종코드 : 6728)을 등록한 업체 또는 "
        "같은 법 시행규칙 제12조 제5항 [별표2] 장비기준을 충족한 업체"
    )

    requirements, diagnostics = _adapt(raw)

    assert requirements == []
    assert diagnostics[0]["code"] == "UNMAPPED_REQUIREMENT"
    assert diagnostics[0].get("reason")  # 가드 사유가 붙는다


def test_the_helper_reports_nothing_when_context_is_missing() -> None:
    """업종코드가 등록·신고 맥락 없이 나오면 살리지 않는다."""
    assert salvage_closed_identifier("업종코드 : 1450 참고") is None
    assert salvage_closed_identifier("영업신고(업종코드 : 1450)") == ("INDUSTRY", "1450")
