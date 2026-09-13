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

한국 공고는 업종 요건에 거의 항상 근거 법령을 붙이므로 첫째는 업종 요건 대부분을
막는다. 골든셋 20공고에서 정답 요건이 판정기에 도달한 비율이 12.5% 였고, 그 큰 이유가
이것이다. 골든셋의 canonical raw 는 법령 인용을 뗀 채 작성돼 있어 골든 러너로는
이 실패가 보이지 않았다 — 제품이 실제로 만들지 않는 모양의 입력이었다.

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

# 조항의 뜻과 무관한 장식. 법령명 인용, 조문 번호, 괄호 안 설명.
_CITATION_RE = re.compile(r"「[^」]*」|『[^』]*』")
_ARTICLE_REF_RE = re.compile(
    r"(?:같은\s*법\s*)?(?:시행령|시행규칙)?\s*제\s*\d+\s*조(?:의\s*\d+)?(?:\s*제\s*\d+\s*항)?(?:\s*제\s*\d+\s*호)?"
    r"(?:\s*\[별표\s*\d*\])?\s*(?:에\s*(?:따른|의한|따라|의거한?)|의)?"
)
_PARENTHETICAL_RE = re.compile(r"\([^()]*\)|（[^（）]*）")


def strip_decorations(raw: str) -> str:
    """법령 인용·조문 번호·괄호 설명을 벗긴 본문. 가드는 이것을 본다.

    괄호를 벗기는 것이 가장 공격적인 선택이다. 괄호 안에 진짜 대안 조건이 들어가는
    공고도 있을 수 있다. 그 경우 이 가드가 아니라 골든셋의 '잘못된 확정' 지표가
    잡아 주므로, 여기서는 흔한 쪽(괄호 = 설명)을 따른다.
    """
    text = _CITATION_RE.sub(" ", raw)
    text = _ARTICLE_REF_RE.sub(" ", text)
    text = _PARENTHETICAL_RE.sub(" ", text)
    return " ".join(text.split())


def unsafe_clause_reason(raw: str) -> str | None:
    """Share conservative source-clause screening with mapping and rules."""
    text = strip_decorations(raw)
    return next((code for pattern, code in _COMPLEX_PATTERNS if re.search(pattern, text)), None)
