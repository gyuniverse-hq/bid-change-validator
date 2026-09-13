"""지역 요건에 위계가 있을 때 판정이 잘못 확정하지 않는지.

2026-07-01 광주·전남 행정통합으로 "전남광주통합특별시" 안에 "종전 광주광역시" 와
"종전 전라남도" 가 생겼다. R26BK01634263 은 003차수에서 소재지를 통합시로 적었다가
004차수에서 "종전 광주광역시" 로 좁혔다. 골든셋 J01/J02/J04 프로필은 통합시 단위라
004 요건에 대해서는 **프로필로 답할 수 없는데**, 부분문자열 비교는 '미달' 을 확정했다.
그 회사가 옛 광주 안에 있으면 틀린 미달이다 — 이 기능에서 가장 나쁜 실패다.
"""

from datetime import date

from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot
from apps.api.app.qualification.rules.judgment import ProfileCompleteness
from apps.api.app.qualification.rules.judgment import judge_requirement


def _region_requirement(value: str) -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key="REQ-REGION",
        notice_version_id="NV-1",
        type="REGION",
        operator="MATCH",
        value=value,
        raw=f"본점소재지를 {value}에 소재한 업체",
    )


def _profile(region_name: str) -> CompanyProfileSnapshot:
    return CompanyProfileSnapshot(
        company_id="C-1",
        region_name=region_name,
        completeness=ProfileCompleteness(region=True),
    )


def _judge(region_name: str, required: str) -> str:
    return judge_requirement(
        _region_requirement(required),
        _profile(region_name),
        preflight_case_id="CASE-1",
        reference_date=date(2026, 7, 15),
    ).status


def test_a_sub_region_requirement_cannot_be_settled_from_a_merged_city_profile() -> None:
    """004차수 상황. 통합시 단위 프로필로는 옛 광주 안인지 알 수 없다 — 미달이 아니라 확인 필요."""
    assert _judge("전남광주통합특별시", "종전 광주광역시") == "UNKNOWN"
    assert _judge("전남광주통합특별시", "종전 전라남도") == "UNKNOWN"


def test_a_sub_region_profile_satisfies_the_merged_city_requirement() -> None:
    """003차수 상황의 반대편. 옛 광주에 있는 회사는 통합시 안에 있다."""
    assert _judge("종전 광주광역시", "전남광주통합특별시") == "SATISFIED"
    # 통합 전 이름으로 등록된 프로필도 같은 하위 지역이다.
    assert _judge("광주광역시", "전남광주통합특별시") == "SATISFIED"
    assert _judge("전라남도", "전남광주통합특별시") == "SATISFIED"


def test_exact_and_unrelated_regions_behave_as_before() -> None:
    assert _judge("전남광주통합특별시", "전남광주통합특별시") == "SATISFIED"
    assert _judge("종전 광주광역시", "종전 광주광역시") == "SATISFIED"
    assert _judge("서울특별시", "종전 광주광역시") == "UNSATISFIED"
    assert _judge("서울특별시", "전남광주통합특별시") == "UNSATISFIED"


def test_the_other_former_region_is_not_confused_with_the_required_one() -> None:
    """옛 전남에 있는 회사는 '종전 광주광역시' 요건에 미달이다 — 위계는 형제 사이를 잇지 않는다."""
    assert _judge("종전 전라남도", "종전 광주광역시") == "UNSATISFIED"
