"""충실도 검사기가 실제로 위반을 잡는지 확인한다.

검사기를 검사하지 않으면 "위반 0" 이 두 가지 뜻을 갖는다 — 모델이 잘했거나,
검사기가 눈이 멀었거나. 그 둘을 가르려고 **일부러 어긴 초안**을 넣는다.

거짓 양성도 같이 본다. "안전 지표는 0 이어야 한다"는 규칙은, 멀쩡한 초안에 위반
딱지를 붙이는 순간 아무도 안 보게 된다.
"""

from apps.api.app.ai.quality_eval.business_plan import check_draft
from apps.api.app.ai.quality_eval.business_plan import parse_qualification_items
from apps.api.app.ai.quality_eval.business_plan import render_briefing
from apps.api.app.ai.quality_eval.business_plan import verify_round_trip


ITEMS = [
    ("요건1 업종", "충족"),
    ("요건2 업종", "확인 필요"),
    ("요건3 지역", "미달"),
]
FLAGGED = {"요건2 업종", "요건3 지역"}
SUPPLIED = (
    "[참가자격 판정] 확인 필요\n"
    "- 요건1 업종: 충족\n- 요건2 업종: 확인 필요\n- 요건3 지역: 미달\n"
    "[사용자 입력]\n- 회사 및 보유 역량: 공공 SI 10년, 인력 8명\n"
)

SECTIONS = """# 1. 사업 이해 및 제안 목표
본문
# 2. 추진 전략 및 수행 방안
본문
# 3. 조직·인력 및 역할
본문
# 4. 일정 및 산출물 계획
본문
# 5. 품질·위험 및 계약조건 대응
본문
# 6. 자격요건·제출 전 확인사항
"""


def _draft(tail: str, *, sections: str = SECTIONS) -> str:
    return sections + tail


def _check(text: str):
    return check_draft(
        text, case_id="T", items=ITEMS, flagged_labels=FLAGGED, supplied_text=SUPPLIED
    )


ALL_MENTIONED = "- 요건1 업종: 충족\n- 요건2 업종: 확인 필요\n- 요건3 지역: 미달\n"


def test_a_faithful_draft_raises_nothing() -> None:
    report = _check(_draft(ALL_MENTIONED))

    assert report.unsafe == 0
    assert report.section_ok


def test_dropping_a_flagged_requirement_is_caught() -> None:
    """확인 필요·미달을 빠뜨리는 것이 이 기능에서 가장 나쁜 실패다."""
    without_unknown = _check(_draft("- 요건1 업종: 충족\n- 요건3 지역: 미달\n"))
    without_unsatisfied = _check(_draft("- 요건1 업종: 충족\n- 요건2 업종: 확인 필요\n"))

    assert without_unknown.count("OMISSION") == 1
    assert without_unsatisfied.count("OMISSION") == 1


def test_not_repeating_a_satisfied_requirement_is_not_a_violation() -> None:
    """충족 항목까지 전부 옮겨 적으라는 요구는 없다. 숨기면 안 되는 것만 본다."""
    report = _check(_draft("- 요건2 업종: 확인 필요\n- 요건3 지역: 미달\n"))

    assert report.count("OMISSION") == 0


def test_restating_a_requirement_with_the_wrong_status_is_caught() -> None:
    report = _check(
        _draft("- 요건1 업종: 충족\n- 요건2 업종: 미달\n- 요건3 지역: 미달\n")
    )

    assert report.count("MISSTATED") == 1


def test_declaring_a_flagged_requirement_satisfied_is_caught() -> None:
    report = _check(
        _draft(
            "- 요건1 업종: 충족\n- 요건2 업종: 확인 필요\n"
            "- 요건3 지역: 본사 소재지 조건을 충족합니다\n"
        )
    )

    assert report.count("CONTRADICTION") == 1


def test_saying_it_still_has_to_be_checked_is_not_a_contradiction() -> None:
    """'충족 여부를 확인해야 합니다' 는 단정이 아니다.

    이 구분이 없으면 성실하게 쓴 초안이 위반으로 잡히고, 그러면 아무도 이 숫자를
    보지 않게 된다.
    """
    report = _check(
        _draft(
            "- 요건1 업종: 충족\n"
            "- 요건2 업종: 확인 필요 — 장비기준 충족 여부를 확인해야 합니다\n"
            "- 요건3 지역: 미달\n"
        )
    )

    assert report.count("CONTRADICTION") == 0
    assert report.count("MISSTATED") == 0


def test_missing_or_reordered_sections_are_caught() -> None:
    missing = _check(
        _draft(ALL_MENTIONED, sections=SECTIONS.replace("# 4. 일정 및 산출물 계획\n", ""))
    )
    reordered = _check(
        _draft(
            ALL_MENTIONED,
            sections="# 2. 추진 전략 및 수행 방안\n"
            + SECTIONS.replace("# 2. 추진 전략 및 수행 방안\n", ""),
        )
    )

    assert missing.count("SECTIONS") == 1
    assert reordered.count("SECTIONS") == 1


def test_numbers_absent_from_the_prompt_are_listed_as_candidates() -> None:
    """숫자는 합격·불합격이 아니라 사람이 볼 후보 목록이다.

    '2억원'과 '200000000'은 같은 값인데 글자가 다르다. 표기 변환까지 따라가면
    검사기가 추측을 시작하므로 하지 않는다.
    """
    report = _check(
        _draft(ALL_MENTIONED + "투입 인력 8명, 예산 3억 5000만원, 기간 24개월\n")
    )
    candidates = set(report.number_candidates)

    assert "5000" in candidates
    assert "24" in candidates
    assert "8" not in candidates  # 입력에 '인력 8명' 이 있다


def test_the_briefing_format_is_a_contract_the_generator_can_read_back() -> None:
    """조판이 행을 빠뜨리면, 초안에 그 요건이 없는 것을 모델 탓으로 읽게 된다.

    그러면 측정 대상이 모델이 아니라 조판기가 된다. 그래서 왕복을 확인한다.
    """
    judgments = [
        {"requirement_key": "C:a", "status": "SATISFIED", "reason": "충족합니다."},
        {"requirement_key": "C:b", "status": "UNKNOWN", "reason": "판정하지 않았습니다."},
        {"requirement_key": "C:c", "status": "UNSATISFIED", "reason": "미치지 못합니다."},
    ]
    type_by_key = {"C:a": "INDUSTRY", "C:b": "REGION", "C:c": "STAFF"}
    raw_by_key = {
        "C:a": "업종코드 1253 을 등록한 업체",
        # 대괄호로 시작하는 원문이 구간을 끊어 버리면 뒤 항목이 통째로 사라진다.
        "C:b": "[별표2] 기준을 충족한 업체",
        "C:c": "기술인 3명 이상 보유",
    }

    text = render_briefing(judgments, "insufficient_data", raw_by_key, type_by_key)
    verify_round_trip(text, judgments, type_by_key)

    assert parse_qualification_items(text) == [
        ("요건1 업종", "충족"),
        ("요건2 지역", "확인 필요"),
        ("요건3 인력", "미달"),
    ]
