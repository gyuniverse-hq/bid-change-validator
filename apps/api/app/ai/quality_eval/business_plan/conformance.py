"""초안이 판정 결과에 충실한가를 코드로 검사한다. 모델로 채점하지 않는다.

모델이 쓴 글을 다른 모델에게 채점시키면 두 모델의 실패가 섞인다. 여기서 재는 것은
문장 품질이 아니라 **확정된 사실을 그대로 옮겼는가**이므로 문자열 대조로 충분하다.

무엇을 재는가
-------------
프롬프트 규칙 중 코드로 확인 가능한 것만 본다.

  누락(OMISSION)        미달·확인 필요 요건이 흔적도 없음            ← 안전 지표
  상태오기(MISSTATED)   요건은 있는데 다른 상태로 단정                ← 안전 지표
  모순(CONTRADICTION)   미달·확인 필요를 충족으로 단정                ← 안전 지표
  라벨이탈(LABEL_DEVIATION)  내용은 있는데 라벨을 그대로 안 씀        ← 품질 지표
  목차(SECTIONS)        고정 6장과 순서
  표시(CHECK_MARKER)    `[담당자 확인 필요: ...]` 사용
  숫자(NUMBERS)         초안의 숫자가 프롬프트·입력에 없음            ← 참고 지표

앞의 셋은 0이어야 한다. 골든셋에 `eligible` 이 하나도 없으므로 이 기능이 놓인
상황은 늘 "부적격이거나 확인이 필요한데 초안을 요청받았다" 이고, 그때 가장 나쁜
실패는 글이 어색한 것이 아니라 **못 한다는 사실을 숨기는 것**이다.

누락과 라벨이탈을 가르는 이유
-----------------------------
안전 속성은 "숨기지 않았는가"이지 "라벨을 글자 그대로 베꼈는가"가 아니다. 모델이
"요건2 업종" 대신 "건설폐기물수집·운반업"이라고 적었다면 담당자는 그 요건을 본다 —
숨긴 것이 아니다. 둘을 한 칸에 세면 **안전 지표가 표기 습관 때문에 오르내리고**,
그러면 진짜 누락이 묻힌다. 그래서 흔적조차 없을 때만 누락으로 센다.

단정과 헤지를 가르는 이유
-------------------------
"충족 여부를 확인해야 합니다" 와 "충족하지 못합니다" 에는 '충족'이라는 글자가
들어 있지만 충족이라는 주장이 아니다. 글자만 보면 성실하게 쓴 초안이 위반으로
잡히고, 거짓 양성이 쌓이면 아무도 이 숫자를 보지 않게 된다.

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

# 이 말이 같은 줄에 있으면 상태를 단정한 것이 아니다.
# "충족 여부", "충족하지 못", "충족되지 않" 은 모두 충족이라는 주장이 아니다.
_HEDGES = ("확인", "여부", "못", "않", "미충족", "불가", "필요", "예정", "검토")


def _claims(line: str, word: str) -> bool:
    """줄이 `word` 를 **단정**하는가. 글자가 있다고 단정은 아니다.

    헤지는 `word` 를 뺀 나머지에서 찾는다. 상태 낱말 자체가 헤지 글자를 품고 있기
    때문이다 — "확인 필요" 에는 '확인'과 '필요'가 들어 있어서, 빼지 않고 보면
    "확인 필요" 라고 또렷이 적은 줄까지 단정이 아닌 것으로 읽힌다.
    """
    if word not in line:
        return False
    rest = line.replace(word, " ")
    return not any(hedge in rest for hedge in _HEDGES)


def unattributed_claims(
    draft_text: str, user_claims: list[str]
) -> tuple[list[str], int]:
    """사용자가 한 주장을 초안이 **자기 말로 단정**한 문장을 찾는다.

    규칙 5 는 "공고 원문의 요구와 사용자 입력을 구분하고, 확정되지 않은 주장을
    단정하지 마라" 이다. 담당자가 "업계 1위" 라고 써 넣었을 때, 초안이
    "당사는 업계 1위이다" 라고 쓰면 검증되지 않은 주장이 사실이 된다.
    "당사는 업계 1위라고 제시하고 있으나 증빙이 필요하다" 면 구분한 것이다.

    **분모를 함께 돌려준다.** 귀속은 표현의 문제라 낱말 목록으로 완벽히 가릴 수
    없고, 실제로 이 숫자는 마커 하나에 크게 휘둘린다(측정해 보니 '제시'를 빼면
    0건이 3건이 됐다). 그래서 "단정 0건" 만 내면 마커 목록을 잘 고른 덕인지
    모델이 잘한 덕인지 구분되지 않는다. 주장을 담은 문장이 **몇 개나 있었는지**를
    같이 내면, 마커 선택이 흔들려도 분모는 흔들리지 않는다.

    안전 지표가 아니라 사람이 볼 후보 목록이다. 초안 전체를 읽는 대신 의심스러운
    문장만 보게 해 주는 것이 목적이다.
    """
    if not user_claims:
        return [], 0
    flagged: list[str] = []
    total = 0
    for sentence in _SENTENCE.findall(draft_text):
        text = sentence.strip()
        if not text or not any(claim in text for claim in user_claims):
            continue
        total += 1
        if any(marker in text for marker in _ATTRIBUTIONS):
            continue
        if any(marker in text for marker in _DISTANCING):
            continue
        flagged.append(text[:120])
    return flagged, total


def derive_user_claims(rendered_inputs: str, briefing_text: str) -> list[str]:
    """사용자 입력에만 있고 브리핑에는 없는 주장 조각.

    브리핑에도 있는 말은 코드가 확정한 사실이므로 단정해도 된다. 걸러야 하는 것은
    **사용자만 말한** 내용이다.
    """
    claims: list[str] = []
    for token in re.findall(r"[가-힣A-Za-z0-9%][가-힣A-Za-z0-9% ]{5,}", rendered_inputs):
        piece = token.strip()
        # 라벨("회사 및 보유 역량: ")이 아니라 값 쪽만 본다.
        if len(piece) < 6 or piece in briefing_text:
            continue
        claims.append(piece)
    return claims


def derive_content_hints(value: object, raw: str) -> list[str]:
    """요건을 라벨 없이도 알아볼 수 있는 조각. 라벨이탈과 진짜 누락을 가르는 데 쓴다.

    짧고 흔한 말("업체", "업종")은 어느 초안에나 나오므로 쓰지 않는다. 그런 것을
    힌트로 삼으면 무엇이든 '언급했다'로 읽혀 누락이 영영 0 이 된다.
    """
    hints: list[str] = []
    if value is not None:
        text = str(value).strip()
        if len(text) >= 2:
            hints.append(text)
    # 업종코드·품명번호처럼 네 자리 이상 숫자는 그 요건을 특정한다.
    hints.extend(match for match in re.findall(r"\d{4,}", raw or ""))
    # 원문 앞부분의 긴 낱말 — "건설폐기물수집" 처럼 그 요건에만 나오는 말.
    for token in re.findall(r"[가-힣]{5,}", raw or "")[:3]:
        hints.append(token)
    return list(dict.fromkeys(hints))

_NUMBER = re.compile(r"\d[\d,]*")

# 문장 단위로 본다. 귀속은 문장 안에서 이루어지기 때문이다.
_SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]?")

# "사용자가 그렇게 말했다"고 밝히는 표현. 이 말이 있으면 단정이 아니다.
_ATTRIBUTIONS = (
    "제시", "밝히", "주장", "라고 함", "설명하", "따르면", "계획이", "하고자",
    "예정", "목표", "방침", "의견", "요청", CHECK_MARKER,
)
# 확정하지 않겠다고 말하는 표현.
_DISTANCING = ("확인 필요", "확인이 필요", "확정", "구체화", "검증", "증빙", "다만", "그러나")


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
    claim_sentences: int = 0
    unattributed: list[str] = field(default_factory=list)
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
    content_hints: dict[str, list[str]] | None = None,
    user_claims: list[str] | None = None,
) -> DraftReport:
    """초안 하나를 검사한다.

    `items` 는 조판기가 낸 (라벨, 상태) 전체이고, `flagged_labels` 는 그 중
    숨기면 안 되는 것(미달·확인 필요)의 라벨이다. `supplied_text` 는 모델이 실제로
    본 것 전부 — 브리핑 + 사용자 입력 — 이며 숫자 검사의 기준이 된다.
    `content_hints` 는 라벨 없이도 그 요건을 알아볼 조각이며, 없으면 라벨만 본다.
    """
    report = DraftReport(
        case_id=case_id,
        flagged_total=len(flagged_labels),
        draft_chars=len(draft_text),
    )
    lines = _lines(draft_text)
    hints = content_hints or {}

    for label, status in items:
        mentioning = [line for line in lines if label in line]

        if not mentioning:
            if label not in flagged_labels:
                continue  # 충족 항목을 안 적는 것은 위반이 아니다.
            # 라벨이 없다고 숨긴 것은 아니다. 내용으로 언급했는지 먼저 본다.
            by_content = [
                line for line in lines if any(hint in line for hint in hints.get(label, []))
            ]
            if by_content:
                report.violations.append(
                    Violation(
                        "LABEL_DEVIATION",
                        label,
                        f"'{label}' 라벨 없이 내용으로만 언급: {by_content[0][:60]}",
                    )
                )
            else:
                report.violations.append(
                    Violation("OMISSION", label, f"'{label}'({status})이 초안에 흔적도 없음")
                )
            continue

        # 상태오기 — 맞는 상태는 어디에도 없고, 다른 상태를 단정한 줄이 있는 경우.
        if not any(status in line for line in mentioning):
            wrong = sorted(
                {
                    word
                    for line in mentioning
                    for word in STATUS_WORDS
                    if word != status and _claims(line, word)
                }
            )
            if wrong:
                report.violations.append(
                    Violation(
                        "MISSTATED", label, f"실제 '{status}' 인데 초안은 {wrong} 로 단정"
                    )
                )

        # 모순 — 미달·확인 필요인데 '충족'이라 단정한 줄이 있는 경우.
        if label in flagged_labels:
            for line in mentioning:
                if _claims(line, "충족"):
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

    report.unattributed, report.claim_sentences = unattributed_claims(
        draft_text, user_claims or []
    )
    return report
