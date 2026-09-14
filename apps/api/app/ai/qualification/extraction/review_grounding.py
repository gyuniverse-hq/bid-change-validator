"""원문 인용을 유일한 실제 구간으로 복원한다. 의미/조건 적용 관계는 판정하지 않는다.

exact 우선, 실패할 때만 비교용 NFKC·공백·장식기호 정규화를 사용한다.
쉼표로 나누거나 떨어진 구간을 합치지 않는다. 저장 인용문은 언제나 원문 slice다.
"""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata

GROUNDING_VERSION = "review-source-grounding-v1"
_TRANSLATE = str.maketrans({"․": "·", "ㆍ": "·", "‧": "·", "・": "·", "‥": "·"})
_DECORATIONS = frozenset("※▶▷◆◇■□●○◦☞‣✓✔★☆")


class SourceQuoteError(ValueError):
    """고정된 코드만 사용한다. 원문/모델 입력을 예외 메시지에 넣지 않는다."""


@dataclass(frozen=True)
class SourceSpan:
    quote: str
    start_offset: int
    end_offset: int
    method: str


def _normalized(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text.translate(_TRANSLATE))
    return "".join(char for char in normalized if not char.isspace() and char not in _DECORATIONS)


def _with_map(source: str) -> tuple[str, list[int]]:
    parts: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(source):
        piece = _normalized(char)
        parts.append(piece)
        origin.extend([index] * len(piece))
    text = "".join(parts)
    # 결합 문자/한글 자모처럼 문자 단위와 전체 NFKC가 다르면 부정확한 좌표를 만들지 않는다.
    # exact 인용은 이 검사 이전에 성공할 수 있다. 지원 범위를 조용히 넓히지 않는다.
    if text != _normalized(source):
        raise SourceQuoteError("UNSUPPORTED_SOURCE_NORMALIZATION")
    return text, origin


def _unique_position(source: str, quote: str) -> int:
    position = source.find(quote)
    if position < 0:
        return -1
    if source.find(quote, position + 1) >= 0:
        raise SourceQuoteError("AMBIGUOUS_SOURCE_QUOTE")
    return position


def _numeric_boundary(source: str, start: int, end: int) -> None:
    # 5억원을 15억원의 뒷부분에서, 3을 1.3의 뒷부분에서 찾았다고 채택하지 않는다.
    if (source[start].isdecimal() and start and
            (source[start - 1].isdecimal() or source[start - 1] in ".,＋+－-억조만천백십")):
        raise SourceQuoteError("PARTIAL_NUMERIC_EXPRESSION")
    if source[end - 1].isdecimal() and end < len(source) and (
            source[end].isdecimal() or source[end] in ".,．，"):
        raise SourceQuoteError("PARTIAL_NUMERIC_EXPRESSION")


def resolve_source_quote(source: str, quote: str, *, base_offset: int = 0) -> SourceSpan:
    """Python 문자 좌표 [start,end). 상위 source/candidate 허용 범위 검사는 호출자 책임.

    장식기호를 무시하는 것은 검색에만 적용한다. 각주/부정/예외의 의미를 무시해도
    된다는 뜻이 아니다. 숫자·쉼표·슬래시·비교/부정/단위 기호는 제거하지 않는다.
    """
    if not isinstance(source, str):
        raise SourceQuoteError("INVALID_SOURCE_TEXT")
    if not isinstance(quote, str) or not quote.strip():
        raise SourceQuoteError("EMPTY_SOURCE_QUOTE")
    if isinstance(base_offset, bool) or not isinstance(base_offset, int) or base_offset < 0:
        raise SourceQuoteError("INVALID_SOURCE_OFFSET")
    if not _normalized(quote):
        raise SourceQuoteError("EMPTY_SOURCE_QUOTE")
    position = _unique_position(source, quote)
    if position >= 0:
        _numeric_boundary(source, position, position + len(quote))
        return SourceSpan(source[position:position + len(quote)], base_offset + position,
                          base_offset + position + len(quote), "EXACT")
    normalized, origin = _with_map(source)
    probe = _normalized(quote)
    position = _unique_position(normalized, probe)
    if position < 0:
        raise SourceQuoteError("QUOTE_NOT_IN_SOURCE")
    end_position = position + len(probe)
    # ㈜ -> (주) 같은 한 문자 확장의 내부 일부만 골라 원문 전체로 바꾸면 잘못된 인용이다.
    if ((position and origin[position - 1] == origin[position])
            or (end_position < len(origin) and origin[end_position] == origin[end_position - 1])):
        raise SourceQuoteError("PARTIAL_NORMALIZED_CHARACTER")
    start, end = origin[position], origin[end_position - 1] + 1
    _numeric_boundary(source, start, end)
    restored = source[start:end]
    if _normalized(restored) != probe:
        raise SourceQuoteError("SOURCE_ROUNDTRIP_MISMATCH")
    return SourceSpan(restored, base_offset + start, base_offset + end, "NORMALIZED")
