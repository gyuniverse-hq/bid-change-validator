"""Shared deterministic source-clause safety screening.

[재현 — 2026-09-13, 홍규형 파일입니다. 아래 두 함수만 더했고 패턴 표는 그대로입니다]

가드가 걸러내는 것과 걸러내면 안 되는 것
----------------------------------------
이 가드는 복합·부정·예외 조건처럼 한 값으로 줄일 수 없는 조항을 UNKNOWN 으로
넘기려고 있다. 그런데 실제 제품 추출 결과에 대 보니 두 패턴이 **조항 자체가 아니라
그 주변 장식**에 걸리고 있었다.

  "「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 건설폐기물중간처리업
   (업종코드 : 1253)을 등록한 업체"
      -> LEGAL_PROCEDURAL_RULE ('법률' 이 있어서). 판정은 업종코드 1253 보유 여부로
         단순하다. 법령 인용은 근거 표시이지 절차 규정이 아니다.

  "본점소재지(개인사업자인 경우 사업자등록증 또는 허가 … 서류가 기재된 사업장의
   소재지)를 전남광주통합특별시에 소재한 업체"
      -> ALTERNATIVE_OR_EXCEPTION_RULE ('또는' 이 있어서). 그 '또는' 은 괄호 안에서
         어느 서류로 주소를 보는지를 설명할 뿐이고, 요건은 '전남광주 소재' 하나다.

한국 공고는 업종 요건에 근거 법령을 자주 붙이므로 첫째는 정상적인 업종 요건까지
막을 수 있다. canonical raw 가 법령 인용을 뗀 형태라면 골든 러너에서도 이 제품 경로
실패가 드러나지 않는다.

그래서 패턴을 대기 전에 **장식을 벗긴다.** 「…」 로 감싼 법령명, 제N조·제N항 같은
조문 번호, 괄호 안 설명을 지운 뒤 같은 패턴을 적용한다. 패턴 표 자체는 손대지 않는다
— 무엇이 위험한 조항인지에 대한 판단은 바뀌지 않았고, 그 판단을 조항이 아닌 곳에
적용하던 것만 고친다.

효과는 골든 러너로 잰다. 잘못된 확정이 0 으로 유지되면서 안전한 보류가 줄어야 한다.
"""

from __future__ import annotations

import re

_COMPLEX_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"〃|상동", "UNRESOLVED_TABLE_REFERENCE"),
    (r"공동수급|공동계약|구성원|대표사|분담이행|공동이행", "COMPOSITE_PARTY_RULE"),
    (r"대표자.*(동일|중복)|중복.*대표자|대표자.*변경등록", "REPRESENTATIVE_CONFLICT_RULE"),
    (r"\b또는\b|\b다만\b|각\s*호|중\s*하나|어느\s*하나", "ALTERNATIVE_OR_EXCEPTION_RULE"),
    (r"관계\s*법령|시행규칙|법률|규정에\s*따라|입찰무효", "LEGAL_PROCEDURAL_RULE"),
    (r"아니어야|하지\s*않아야|아닌\s*자|제외한다|제외됨", "NEGATED_RULE"),
    (r"계약.*해지|낙찰자.*결정|제한을\s*받는", "POST_AWARD_OR_RESTRICTION_RULE"),
)

# 조항의 뜻과 무관한 장식. 법령명 인용, 조문 번호, 주소 증빙 설명 괄호.
#
# 따옴표는 두 조건을 다 만족할 때만 벗긴다 — 안이 법령명 꼴이고, 바로 뒤에 인용 문맥
# (제N조 · 에 따른 · 에 의거 …)이 붙을 때. 「…」 는 법령 인용에 쓰이지만 조건을 감싸는
# 데도 쓰인다. 「소기업 또는 소상공인」 을 지우면 '또는' 이 가드에 닿기 전에 사라지고
# (#128 1차 리뷰), '기준' 을 법령 접미로 두면 「소기업 또는 소상공인 기준」 도 지워진다
# (2차 리뷰). 접미 하나로는 못 가르므로 뒤따르는 인용 문맥까지 요구한다.
_QUOTED_RE = re.compile(
    r"(?:「(?P<a>[^」]*)」|『(?P<b>[^』]*)』)"
    r"(?P<ctx>\s*(?:(?:시행령|시행규칙|같은\s*법)?\s*제\s*\d+\s*(?:조|장)"
    r"|에\s*(?:따른|따라|의한|의하여|의거한?|근거한?)|상\b|에서\s*정한))?"
)
_STATUTE_NAME_RE = re.compile(
    r"(?:에\s*관한\s*법률|법률|법|시행령|시행규칙|규칙|조례|규정|고시|지침|예규|훈령)\s*$"
)
_ARTICLE_REF_RE = re.compile(
    r"(?:같은\s*법\s*)?(?:시행령|시행규칙)?\s*제\s*\d+\s*조(?:의\s*\d+)?(?:\s*제\s*\d+\s*항)?(?:\s*제\s*\d+\s*호)?"
    r"(?:\s*\[별표\s*\d*\])?\s*(?:에\s*(?:따른|의한|따라|의거한?)|의)?"
)
_PARENTHETICAL_RE = re.compile(r"\((?P<ascii>[^()]*)\)|（(?P<fullwidth>[^（）]*)）")
# 괄호는 기본 보존한다. 주소를 어느 서류로 보는지 나열한 설명 괄호만 벗긴다.
# "사업자등록증 또는 허가 서류" 만으로는 부족하다 — "(사업자등록증 또는 허가 서류 제출)"
# 은 실제 대안 제출 조건이라 '또는' 이 가드에 남아야 한다 (#128 2차 리뷰). 주소 설명은
# 반드시 '사업장' 과 '소재지' 를 함께 말하므로 그 둘을 요구한다.
_ADDRESS_EVIDENCE_OR_RE = re.compile(
    r"(?:사업자등록증|법인등기부(?:등본)?)\s*또는\s*"
    r"(?:허가|인가|면허|등록|신고)[^()]*사업장[^()]*소재지"
)


def _strip_quoted(match: re.Match[str]) -> str:
    inner = (match.group("a") or match.group("b") or "").strip()
    if _STATUTE_NAME_RE.search(inner) and match.group("ctx"):
        return " "
    return match.group(0)


def _strip_parenthetical(match: re.Match[str]) -> str:
    inner = match.group("ascii") or match.group("fullwidth") or ""
    return " " if _ADDRESS_EVIDENCE_OR_RE.search(inner) else match.group(0)


def strip_decorations(raw: str) -> str:
    """법령명 인용·조문 번호·주소 증빙 설명 괄호를 벗긴 본문. 가드는 이것을 본다.

    벗기는 것은 셋뿐이고 나머지는 전부 남긴다. 조건을 감싼 따옴표, 제한을 적은 괄호가
    사라지면 가드가 우회되므로, 무엇을 지울지가 아니라 무엇만 지울지를 정한다.
    """
    text = _QUOTED_RE.sub(_strip_quoted, raw)
    text = _ARTICLE_REF_RE.sub(" ", text)
    text = _PARENTHETICAL_RE.sub(_strip_parenthetical, text)
    return " ".join(text.split())


def unsafe_clause_reason(raw: str) -> str | None:
    """Share conservative source-clause screening with mapping and rules."""
    text = strip_decorations(raw)
    return next((code for pattern, code in _COMPLEX_PATTERNS if re.search(pattern, text)), None)
