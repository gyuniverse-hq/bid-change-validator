"""초안이 판정 결과에 충실한가를 코드로 검사한다. 모델로 채점하지 않는다.

모델이 쓴 글을 다른 모델에게 채점시키면 두 모델의 실패가 섞인다. 여기서 재는 것은
문장 품질이 아니라 **확정된 사실을 그대로 옮겼는가**이므로 문자열 대조로 충분하다.

무엇을 재는가
-------------
프롬프트 규칙 중 코드로 확인 가능한 것만 본다.

  누락(OMISSION)        미달·확인 필요 요건이 초안에 아예 없음        ← 안전 지표
  상태오기(MISSTATED)   요건은 있는데 다른 상태로 적음                ← 안전 지표
  모순(CONTRADICTION)   미달·확인 필요를 충족으로 단정                ← 안전 지표
  목차(SECTIONS)        고정 6장과 순서
  표시(CHECK_MARKER)    `[담당자 확인 필요: ...]` 사용
  숫자(NUMBERS)         초안의 숫자가 프롬프트·입력에 없음            ← 참고 지표

앞의 셋은 0이어야 한다. 골든셋에 `eligible` 이 하나도 없으므로 이 기능이 놓인
상황은 늘 "부적격이거나 확인이 필요한데 초안을 요청받았다" 이고, 그때 가장 나쁜
실패는 글이 어색한 것이 아니라 **못 한다는 사실을 숨기는 것**이다.

숫자 검사의 한계를 먼저 적어 둔다
---------------------------------
"2억원"과 "200000000"은 같은 값인데 글자가 다르다. 표기 변환까지 따라가면 검사기
자체가 추측을 시작하므로 하지 않는다. 그래서 숫자는 합격/불합격이 아니라 **후보**로
보고한다. 사람이 볼 목록을 줄여 주는 용도다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field


REQUIRED_SECTIONS = (
    "# 1. 사업 이해 및 제안 목표",
    "# 2. 추진 전략 및 수행 방안",
    "# 3. 조직·인력 및 역할",
    "# 4. 일정 및 산출물 계획",
    "# 5. 품질·위험 및 계약조건 대응",
    "# 6. 자격요건·제출 전 확인사항",
)

CHECK_MARKER = "[담당자 확인 필요:"

# 화면 문구와 같은 3상태. 상태오기 검사는 이 세 낱말만 본다.
STATUS_WORDS = ("충족", "미달", "확인 필요")

# "충족"으로 단정했는지 볼 때, 이 말이 같은 줄에 있으면 단정이 아니다.
_HEDGES = ("미달", "확인 필요", "확인이 필요", "확인 필", "미충족", "불가", "여부", "못", "않")

_NUMBER = re.compile(r"\d[\d,]*")


@dataclass
class Violation:
    kind: str
    requirement_label: str | None
    detail: str


@dataclass
class DraftReport:
    case_id: str
    flagged_total: int
    violations: list[Violation] = field(default_factory=list)
    section_ok: bool = True
    check_marker_count: int = 0
    number_candidates: list[str] = field(default_factory=list)
    draft_chars: int = 0

    def count(self, kind: str) -> int:
        return sum(1 for v in self.violations if v.kind == kind)

    @property
    def unsafe(self) -> int:
        """0 이어야 하는 것들의 합."""
        return sum(self.count(k) for k in ("OMISSION", "MISSTATED", "CONTRADICTION"))


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def check_draft(
    draft_text: str,
    *,
    case_id: str,
    items: list[tuple[str, str]],
    flagged_labels: set[str],
    supplied_text: str,
) -> DraftReport:
    """초안 하나를 검사한다.

    `items` 는 조판기가 낸 (라벨, 상태) 전체이고, `flagged_labels` 는 그 중
    숨기면 안 되는 것(미달·확인 필요)의 라벨이다. `supplied_text` 는 모델이 실제로
    본 것 전부 — 브리핑 + 사용자 입력 — 이며 숫자 검사의 기준이 된다.
    """
    report = DraftReport(
        case_id=case_id,
        flagged_total=len(flagged_labels),
        draft_chars=len(draft_text),
    )
    lines = _lines(draft_text)

    for label, status in items:
        mentioning = [line for line in lines if label in line]

        if label in flagged_labels and not mentioning:
            report.violations.append(
                Violation("OMISSION", label, f"'{label}'({status})이 초안에 전혀 없음")
            )
            continue
        if not mentioning:
            continue  # 충족 항목을 안 적는 것은 위반이 아니다.

        # 상태오기 — 라벨과 같은 줄에 '다른' 상태 낱말만 있는 경우.
        if not any(status in line for line in mentioning):
            wrong = sorted(
                {word for line in mentioning for word in STATUS_WORDS if word in line}
            )
            if wrong:
                report.violations.append(
                    Violation(
                        "MISSTATED",
                        label,
                        f"실제 '{status}' 인데 초안은 {wrong} 로 적음",
                    )
                )

        # 모순 — 미달·확인 필요인데 '충족'이라 단정한 줄이 있는 경우.
        if label in flagged_labels:
            for line in mentioning:
                if "충족" in line and not any(hedge in line for hedge in _HEDGES):
                    report.violations.append(
                        Violation("CONTRADICTION", label, f"'{status}'인데 충족 단정: {line[:70]}")
                    )
                    break

    positions = [draft_text.find(section) for section in REQUIRED_SECTIONS]
    report.section_ok = all(p >= 0 for p in positions) and positions == sorted(positions)
    if not report.section_ok:
        missing = [s for s, p in zip(REQUIRED_SECTIONS, positions) if p < 0]
        report.violations.append(
            Violation("SECTIONS", None, f"누락 {missing}" if missing else "순서 어긋남")
        )

    report.check_marker_count = draft_text.count(CHECK_MARKER)

    supplied_numbers = {m.replace(",", "") for m in _NUMBER.findall(supplied_text)}
    for match in _NUMBER.findall(draft_text):
        normalized = match.replace(",", "")
        if len(normalized) >= 2 and normalized not in supplied_numbers:
            report.number_candidates.append(match)

    return report
