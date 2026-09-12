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
# 모델은 대괄호 대신 불릿으로도 쓴다 — "- 담당자 확인 필요: ...".
# 대괄호만 세다가 표시를 13개나 단 초안을 "0개"로 읽었다. 초안을 직접 읽다 발견했다.
_CHECK_MARKER_ANY = re.compile(r"담당자\s*확인\s*필요\s*:")

# 화면 문구와 같은 3상태. 상태오기 검사는 이 세 낱말만 본다.
STATUS_WORDS = ("충족", "미달", "확인 필요")

# 이 말이 같은 줄에 있으면 상태를 단정한 것이 아니다.
# "충족 여부", "충족하지 못", "충족되지 않" 은 모두 충족이라는 주장이 아니다.
_HEDGES = ("확인", "여부", "못", "않", "미충족", "불가", "필요", "예정", "검토")


# '충족'이 서술어 자리에 있을 때만 단정이다.
#   단정      "조건을 충족합니다" "요건을 충족한다"
#   단정 아님  "충족하는 항목을 선택한다" "충족한다고 판단하는" "충족 항목 확보"
# 관형형(충족하는·충족할)과 인용형(-고)은 담당자에게 고르라는 지시이지 주장이 아니다.
_SATISFIED_CLAIM = re.compile(
    r"충족(?:합니다|했|하였|한다(?!고)|됩니다|되었|된다(?!고)|함\b|임\b|으로\s*판정)"
)


def _segment_for(line: str, label: str, other_labels: list[str]) -> str:
    """한 줄에 여러 요건이 적혔을 때, 이 라벨 몫만 잘라낸다.

    "요건1 업종: 충족으로 판정되었으나, 요건2 실적 금액: 미달" 같은 줄에서 줄 전체를
    보면 요건2 에도 '충족'이 붙어 모순으로 잡힌다. 실제로 그렇게 오검출됐다.
    """
    start = line.find(label)
    if start < 0:
        return line
    end = len(line)
    for other in other_labels:
        if other == label:
            continue
        position = line.find(other, start + len(label))
        if position >= 0:
            end = min(end, position)
    return line[start:end]


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

    이것은 지표가 아니라 **읽을 거리를 줄여 주는 장치**다. 정밀도를 재 봤고,
    낮다는 것을 확인했다
    -------------------------------------------------------------------
    288건을 돌려 나온 후보 54건 중 11건을 직접 읽어 보니 최소 9건이 거짓 양성이었다.
    모델은 마커 목록에 없는 방식으로 계속 귀속한다 — "회사 제공 계획에 따라",
    "회사 설명을", "과도한 표현은 ... 조정" 같은 식이다. 마커를 더 붙이면 이 데이터에만
    맞아 들어갈 뿐이다.

    민감도도 크다. '제시' 한 낱말만 빼도 0건이 3건이 됐다. 그래서 **분모(주장을 담은
    문장 수)를 함께 돌려준다.** 분모는 마커 선택에 흔들리지 않으므로, 후보 수가
    마커를 잘 고른 덕인지 모델이 잘한 덕인지 구분하는 데 쓸 수 있다.

    쓰는 법: 안전 지표처럼 "0 이어야 한다"고 읽지 말 것. 초안 288편을 다 읽는 대신
    이 문장들만 훑어보라는 목록이다. 진짜 판단은 사람이 한다.
    """
    if not user_claims:
        return [], 0
    flagged: list[str] = []
    total = 0
    for sentence in _SENTENCE.findall(draft_text):
        text = sentence.strip()
        present = [claim for claim in user_claims if claim in text]
        if not text or not present:
            continue
        total += 1
        if any(marker in text for marker in _ATTRIBUTIONS):
            continue
        if any(marker in text for marker in _DISTANCING):
            continue
        # 따옴표 안의 표현은 **그 말을 다루는 것**이지 주장하는 것이 아니다.
        # 실제로 초안들이 «"100% 성공 보장" 과 같은 표현은 ... 조정한다» 처럼
        # 사용자의 과장을 인용해 고치라고 적었는데, 그것까지 단정으로 셌었다.
        if all(_is_quoted(text, claim) for claim in present):
            continue
        flagged.append(text[:120])
    return flagged, total


_QUOTES = ('"', "'", "“", "”", "‘", "’", "「", "」", "«", "»")


def _is_quoted(text: str, claim: str) -> bool:
    """`claim` 이 따옴표 안에 있는가 — 주장이 아니라 인용이라는 신호."""
    position = text.find(claim)
    if position < 0:
        return False
    before = text[:position]
    after = text[position + len(claim) :]
    return any(q in before for q in _QUOTES) and any(q in after for q in _QUOTES)


# 검증할 수 없는데 단정하면 곤란한 말들. 최상급·절대·보장 표현이다.
# "PM 1명" 같은 평범한 입력까지 주장으로 세면, 사업계획서 내용 대부분이 원래
# 사용자가 준 것이라 분모가 초안 길이를 따라가 버린다. 실제로 그렇게 재 보니
# FULL 입력에서만 1,049 문장이 잡혔다 — 그 숫자는 아무것도 말해 주지 않는다.
_SUPERLATIVES = (
    "1위", "최다", "최고", "최상", "최대", "유일", "독보",
    "100%", "완벽", "보장", "압도", "무제한", "절반", "무결",
    "국내 최", "업계 최", "경쟁사 대비", "모든 참가자격",
)


def derive_user_claims(rendered_inputs: str, briefing_text: str) -> list[str]:
    """사용자만 말한 **검증 불가능한 주장**. 평범한 입력은 세지 않는다.

    브리핑에도 있는 말은 코드가 확정한 사실이므로 단정해도 된다. 문제는 사용자가
    자기 입으로만 한 말이고, 그 중에서도 확인할 길이 없는 최상급·절대 표현이다.

    조각은 **짧아야 한다.** 문장을 통째로 담으면 초안에서 같은 문장을 찾을 일이
    없어 아무것도 걸리지 않는다 — 실제로 그렇게 만들었다가 288건 전부 0 이 나왔다.
    그래서 사용자가 실제로 쓴 최상급 표현 자체를 조각으로 삼는다.
    """
    claims: list[str] = []
    for line in rendered_inputs.splitlines():
        _, _, value = line.partition(": ")
        value = value.strip()
        if not value or value in briefing_text:
            continue
        claims.extend(word for word in _SUPERLATIVES if word in value)
    return list(dict.fromkeys(claims))


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
    all_labels = [label for label, _ in items]

    for label, status in items:
        mentioning = [line for line in lines if label in line]
        # 한 줄에 여러 요건이 적힌 경우가 흔하다. 이 라벨 몫만 떼어 놓고 본다.
        segments = [_segment_for(line, label, all_labels) for line in mentioning]

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
        if not any(status in segment for segment in segments):
            wrong = sorted(
                {
                    word
                    for segment in segments
                    for word in STATUS_WORDS
                    if word != status and _claims(segment, word)
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
            for segment in segments:
                # 서술어 자리의 '충족'만 단정으로 센다. "충족하는 항목을 선택" 은
                # 담당자에게 고르라는 지시이지 요건을 채웠다는 주장이 아니다.
                if _SATISFIED_CLAIM.search(segment) and _claims(segment, "충족"):
                    report.violations.append(
                        Violation("CONTRADICTION", label, f"'{status}'인데 충족 단정: {segment[:70]}")
                    )
                    break

    positions = [draft_text.find(section) for section in REQUIRED_SECTIONS]
    report.section_ok = all(p >= 0 for p in positions) and positions == sorted(positions)
    if not report.section_ok:
        missing = [s for s, p in zip(REQUIRED_SECTIONS, positions) if p < 0]
        report.violations.append(
            Violation("SECTIONS", None, f"누락 {missing}" if missing else "순서 어긋남")
        )

    report.check_marker_count = len(_CHECK_MARKER_ANY.findall(draft_text))

    supplied_numbers = {m.replace(",", "") for m in _NUMBER.findall(supplied_text)}
    for match in _NUMBER.findall(draft_text):
        normalized = match.replace(",", "")
        if len(normalized) >= 2 and normalized not in supplied_numbers:
            report.number_candidates.append(match)

    report.unattributed, report.claim_sentences = unattributed_claims(
        draft_text, user_claims or []
    )
    return report
