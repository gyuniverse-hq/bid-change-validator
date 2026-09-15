"""판정 결과 JSON -> 모델 프롬프트에 들어갈 문자열. 모델은 쓰지 않는다.

여기는 조판만 한다. 판정은 이미 `rules.judge_requirements` 가 끝냈고, 그 결과가
골든셋 실행 스냅샷에 JSON 으로 남아 있다. 이 모듈은 그것을 사람이 읽는 줄로
엮을 뿐이며 해석하거나 요약하지 않는다.

왜 코드로 조판하나
------------------
여기에 모델을 한 번 더 끼우면 초안에서 요건이 빠졌을 때 범인이 둘이 된다 —
요약 모델이 버렸는지, 초안 모델이 무시했는지. 조판이 결정적이면 범인은 하나다.
반복 측정에서 나타나는 분산도 전부 초안 모델 몫으로 돌릴 수 있다.

형식은 계약이다
---------------
초안 생성기(`business_plan.py::_qualification_items`)가 이 문자열을 되읽어
항목 누락·변형을 검사한다. 그 파서는 이렇게 읽는다:

    "[참가자격 판정]" 이후 "\\n[" 전까지가 구간
    그 안에서 "- " 로 시작하고 ":" 가 있는 줄만 (라벨, 상태) 로 취한다

따라서 항목 줄 외에는 "- " 로 시작해서는 안 된다. 형식이 어긋나면 파서가 빈
리스트를 반환하고, 그러면 검사가 조용히 통과한다 — 가장 나쁜 실패다.
`parse_qualification_items()` 가 그 파서를 그대로 흉내내고,
`verify_round_trip()` 이 모든 행이 되읽히는지 확인한다.

문구는 화면과 같아야 한다
-------------------------
`apps/web/lib/status-copy.ts` 의 문구를 그대로 옮겼다. 초안은 화면과 나란히
읽히므로 같은 판정을 다른 말로 부르면 사용자가 다른 결과로 읽는다.
"""

from __future__ import annotations

import re


# apps/web/lib/status-copy.ts 와 글자까지 같아야 한다.
JUDGMENT_STATUS_LABEL = {
    "SATISFIED": "충족",
    "UNSATISFIED": "미달",
    "UNKNOWN": "확인 필요",
}
OVERALL_STATUS_LABEL = {
    "eligible": "참가 가능",
    "ineligible": "참가 불가",
    "insufficient_data": "확인 필요",
}
REQUIREMENT_TYPE_LABEL = {
    "INDUSTRY": "업종",
    "REGION": "지역",
    "PERFORMANCE_COUNT": "실적 건수",
    "PERFORMANCE_AMOUNT": "실적 금액",
    "EXPERIENCE_FIELD": "수행 분야",
    "STAFF": "인력",
    "COMPANY_SIZE": "기업규모",
    "REGISTRATION_CERTIFICATION": "등록·인증",
}

QUALIFICATION_MARKER = "[참가자격 판정]"
_ITEM_LINE = re.compile(r"^- (?P<label>[^:]+):\s*(?P<status>.+)$")


def item_label(index: int, requirement_type: str) -> str:
    """항목 라벨. 모델이 글자 그대로 베껴 쓸 수 있을 만큼 짧아야 한다.

    원문(raw)을 라벨로 쓰면 중앙값 31자에 최대 221자라 잘라야 하고, 자르면 모델이
    뒷부분을 제 나름대로 채워서 글자 대조가 깨진다. 유형만 쓰면 한 공고에 업종이
    셋인 경우 구분이 안 된다. 그래서 번호를 붙인다. 원문은 라벨이 아니라 항목
    아래 별도 줄에 그대로 싣는다.
    """
    korean = REQUIREMENT_TYPE_LABEL.get(requirement_type, requirement_type)
    return f"요건{index} {korean}"


def render_briefing(
    judgments: list[dict],
    overall_status: str,
    raw_by_key: dict[str, str],
    type_by_key: dict[str, str],
    *,
    notice_title: str | None = None,
) -> str:
    """판정 결과를 프롬프트 문자열로 엮는다. 어떤 행도 버리지 않는다."""
    lines: list[str] = []
    if notice_title:
        lines.append(f"[공고] {notice_title}")
        lines.append("")

    overall = OVERALL_STATUS_LABEL.get(overall_status, overall_status)
    lines.append(f"{QUALIFICATION_MARKER} {overall}")

    for index, judgment in enumerate(judgments, start=1):
        key = judgment["requirement_key"]
        label = item_label(index, type_by_key.get(key, ""))
        status = JUDGMENT_STATUS_LABEL.get(judgment["status"], judgment["status"])
        lines.append(f"- {label}: {status}")

        raw = " ".join((raw_by_key.get(key) or "").split())
        if raw:
            # "- " 로 시작하지 않아야 파서가 항목으로 오인하지 않는다.
            lines.append(f"    공고 원문: {raw}")
        reason = (judgment.get("reason") or "").strip()
        if reason:
            lines.append(f"    판정 근거: {reason}")
        refs = judgment.get("profile_refs") or []
        if refs:
            shown = ", ".join(
                f"{ref.get('kind')}.{ref.get('field')}={ref.get('value')}" for ref in refs
            )
            lines.append(f"    회사 정보: {shown}")

    lines.append("")
    return "\n".join(lines)


def parse_qualification_items(briefing_text: str) -> list[tuple[str, str]]:
    """초안 생성기의 파서를 그대로 흉내낸다 — 형식 계약을 지키는지 확인하려고."""
    start = briefing_text.find(QUALIFICATION_MARKER)
    if start < 0:
        return []
    section = briefing_text[start + len(QUALIFICATION_MARKER) :]
    end = section.find("\n[")
    if end >= 0:
        section = section[:end]

    items: list[tuple[str, str]] = []
    for line in section.splitlines():
        candidate = line.strip()
        if not candidate.startswith("- ") or ":" not in candidate:
            continue
        label, status = candidate[2:].split(":", 1)
        label, status = label.strip(), status.strip()
        if label and status:
            items.append((label, status))
    return items


def verify_round_trip(briefing_text: str, judgments: list[dict], type_by_key: dict[str, str]) -> None:
    """조판한 모든 판정 행이 되읽히는지 확인한다.

    이 검사가 없으면, 조판이 행을 빠뜨렸을 때 초안에 그 요건이 없는 것을 두고
    모델이 숨겼다고 읽게 된다. 측정 대상이 모델이 아니라 조판기가 되어 버린다.
    """
    items = parse_qualification_items(briefing_text)
    expected = [
        (
            item_label(index, type_by_key.get(j["requirement_key"], "")),
            JUDGMENT_STATUS_LABEL.get(j["status"], j["status"]),
        )
        for index, j in enumerate(judgments, start=1)
    ]
    if items != expected:
        raise AssertionError(
            "조판 형식 계약 위반 — 생성기 파서가 판정 행을 그대로 되읽지 못한다.\n"
            f"  기대 {len(expected)}행: {expected}\n"
            f"  실제 {len(items)}행: {items}"
        )
