"""안전 가드가 조항의 장식(법령 인용·조문 번호·괄호 설명)이 아니라 조항 자체를 보는지.

제품 추출 결과를 골든셋과 대조해 보니, 정답 요건이 판정기에 도달한 비율이 12.5% 였고
가장 큰 이유가 이 가드였다. "「…법률」 제21조에 따른 건설폐기물중간처리업(업종코드
1253)을 등록한 업체" 는 판정이 업종코드 보유 여부로 단순한데 '법률' 이 있어서
절차 규정으로 막혔다. 골든셋 canonical raw 는 인용을 뗀 채 작성돼 있어 골든 러너로는
이 실패가 보이지 않았다.

장식을 벗긴 뒤 같은 패턴을 대면 골든 러너에서 정답 일치 104 -> 110, 안전한 보류
34 -> 28, 잘못된 확정 0 -> 0 이다. 여기서는 그 경계를 고정한다 — 장식은 통과시키고
진짜 복합·부정·절차 조항은 여전히 막는다.
"""

from apps.api.app.qualification.rules.clause_safety import strip_decorations
from apps.api.app.qualification.rules.clause_safety import unsafe_clause_reason


def test_a_statute_citation_is_not_a_procedural_rule() -> None:
    """실제 제품 추출 결과. 법령 인용은 근거 표시이지 절차 규정이 아니다."""
    raw = (
        "나. 「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 "
        "건설폐기물중간처리업 (업종코드 : 1253)을 등록한 업체"
    )

    assert unsafe_clause_reason(raw) is None


def test_an_alternative_inside_a_parenthetical_is_not_an_alternative_requirement() -> None:
    """골든셋 J01~J04 region. 괄호 안 '또는' 은 어느 서류로 주소를 보는지의 설명이다."""
    raw = (
        "본점소재지(개인사업자인 경우 사업자등록증 또는 허가․ 인가․면허․등록․신고 등에 "
        "관련된 서류가 기재된 사업장의 소재지)를 전남광주통합특별시에 소재한 업체"
    )

    assert unsafe_clause_reason(raw) is None


def test_a_real_alternative_in_the_main_clause_is_still_guarded() -> None:
    """골든셋 transport (REVIEW_HELD). '등록한 업체 또는 장비기준을 충족한 업체' 는 진짜 대안이다."""
    raw = (
        "다. 「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 건설폐기물수집·운반업 "
        "(업종코드 : 6728)을 등록한 업체 또는 같은 법 시행규칙 제12조 제5항 [별표2] 1. 가. "
        "수집·운반업 허가기준의 장비기준을 충족한 업체"
    )

    assert unsafe_clause_reason(raw) == "ALTERNATIVE_OR_EXCEPTION_RULE"


def test_real_procedural_negated_and_composite_rules_are_still_guarded() -> None:
    assert unsafe_clause_reason("관계법령에 따라 입찰무효 처리한다") == "LEGAL_PROCEDURAL_RULE"
    assert unsafe_clause_reason("대기업이 아닌 자") == "NEGATED_RULE"
    assert unsafe_clause_reason("공동수급체 구성원 각각 등록") == "COMPOSITE_PARTY_RULE"


def test_stripping_removes_decorations_but_keeps_the_clause() -> None:
    stripped = strip_decorations(
        "「지방자치단체를 당사자로 하는 계약에 관한 법률」 시행령 제20조 및 같은 법 시행규칙 "
        "제24조에 따라 공고일 전일(법인등기일 기준)부터 본점이 전남에 있는 업체"
    )

    assert "법률" not in stripped
    assert "제20조" not in stripped and "제24조" not in stripped
    assert "법인등기일" not in stripped
    assert "본점이 전남에 있는 업체" in stripped
