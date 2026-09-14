"""원문에서 확인된 수치 표현을 역할별 피연산자로 정규화한다.

역할 선택은 호출자/후속 의미 검증의 책임이다. 숫자가 있다는 이유로 자격요건을 만들지 않는다.
한 표현만 파싱하며 복수 기간/금액의 합성, 근사치, 불명확한 기준일은 추정하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
import re
import unicodedata

OPERAND_VERSION = "review-operands-v1"
_ROLES = frozenset({"LOOKBACK_WINDOW", "OPERATION_DURATION", "PERFORMANCE_AMOUNT",
                    "BUDGET_AMOUNT", "PERFORMANCE_COUNT", "STAFF_COUNT", "DAILY_VOLUME"})
_OP = {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}
_NUMBER = r"(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
_SCALE = {"": 1, "십": 10, "백": 100, "천": 1000, "만": 10000, "십만": 100000,
          "백만": 1000000, "천만": 10000000, "억": 100000000, "조": 1000000000000}
_ANCHORS = frozenset({"NOTICE_DATE", "SUBMISSION_DEADLINE", "CONTRACT_START"})


class OperandError(ValueError):
    """정규화를 추측하는 대신 고정 오류 코드를 반환한다."""


@dataclass(frozen=True)
class SourceOperand:
    role: str
    operator: str
    value: int
    unit: str
    source_candidate_id: str
    start_offset: int
    end_offset: int
    quote: str
    # VAT UNSPECIFIED와 기준일 미지정은 추정값이 아니다.
    tax_basis: str = "UNSPECIFIED"
    anchor: str | None = None

    def semantic_payload(self) -> dict[str, object]:
        return {"version": OPERAND_VERSION, "role": self.role, "operator": self.operator,
                "value": self.value, "unit": self.unit, "tax_basis": self.tax_basis,
                "anchor": self.anchor}


def _whole(value: Decimal) -> int:
    if not value.is_finite() or value < 0 or value != value.to_integral_value():
        raise OperandError("NON_INTEGRAL_OPERAND")
    return int(value)


def parse_source_operand(*, role: str, quote: str, source_candidate_id: str,
                         start_offset: int, end_offset: int,
                         anchor: str | None = None) -> SourceOperand:
    """resolve_source_quote가 반환한 실제 인용과 좌표를 입력한다.

    이 함수의 파싱 성공만으로 해당 값이 특정 요건의 값임을 보증하지 않는다.
    역할이 없는 숫자, 비교연산자 없는 임계값, 여러 표현은 실패한다.
    """
    if not isinstance(role, str) or role not in _ROLES:
        raise OperandError("UNSUPPORTED_OPERAND_ROLE")
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 1000:
        raise OperandError("INVALID_OPERAND_QUOTE")
    if not isinstance(source_candidate_id, str) or not source_candidate_id.strip():
        raise OperandError("INVALID_OPERAND_SOURCE")
    if (any(isinstance(n, bool) or not isinstance(n, int) for n in (start_offset, end_offset))
            or start_offset < 0 or end_offset - start_offset != len(quote)):
        raise OperandError("INVALID_OPERAND_SPAN")
    if anchor is not None and (not isinstance(anchor, str) or anchor not in _ANCHORS):
        raise OperandError("UNKNOWN_TIME_ANCHOR")
    if anchor is not None and role != "LOOKBACK_WINDOW":
        raise OperandError("UNEXPECTED_TIME_ANCHOR")
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", quote))
    tax_basis = "UNSPECIFIED"
    if role in {"PERFORMANCE_AMOUNT", "BUDGET_AMOUNT"}:
        # 인용 내부에 명시된 세금 조건만 읽는다. 서로 다른 세금 기준은 별도 요건이다.
        tax = re.findall(r"\((?:부가세|부가가치세)(포함|별도|제외)\)", text)
        if len(tax) > 1:
            raise OperandError("MULTIPLE_TAX_EXPRESSIONS")
        if tax:
            tax_basis = "INCLUDED" if tax[0] == "포함" else "EXCLUDED"
            text = re.sub(r"\((?:부가세|부가가치세)(?:포함|별도|제외)\)", "", text)
        match = re.fullmatch(rf"(?P<n>{_NUMBER})(?P<scale>천만|백만|십만|조|억|만|천|백|십)?원(?P<op>이상|초과|이하|미만)", text)
        unit, multiplier = "KRW", None
        if match:
            multiplier = _SCALE[match["scale"] or ""]
    elif role == "LOOKBACK_WINDOW":
        match = re.fullmatch(rf"최근(?P<n>{_NUMBER})(?P<unit>년|개월|월)(?:간|이내)?", text)
        unit, multiplier = "MONTH", None
        if match:
            multiplier = 12 if match["unit"] == "년" else 1
    elif role == "OPERATION_DURATION":
        match = re.fullmatch(rf"(?P<n>{_NUMBER})(?P<unit>년|개월|월)(?P<op>이상|초과|이하|미만)", text)
        unit, multiplier = "MONTH", None
        if match:
            multiplier = 12 if match["unit"] == "년" else 1
    else:
        units = {"PERFORMANCE_COUNT": "건|개|회", "STAFF_COUNT": "명", "DAILY_VOLUME": "식"}
        prefix = r"(?:1일|일일)(?:평균)?" if role == "DAILY_VOLUME" else ""
        match = re.fullmatch(rf"{prefix}(?P<n>{_NUMBER})(?P<unit>{units[role]})(?P<op>이상|초과|이하|미만)", text)
        unit, multiplier = {"PERFORMANCE_COUNT": "COUNT", "STAFF_COUNT": "PERSON",
                            "DAILY_VOLUME": "MEAL_PER_DAY"}[role], 1
    if match is None or multiplier is None:
        raise OperandError("UNSUPPORTED_OR_MULTIPLE_OPERAND_EXPRESSIONS")
    number = match["n"].replace(",", "")
    # Decimal 기본 precision을 넘는 입력을 반올림해 다른 금액으로 저장하지 않는다.
    with localcontext() as context:
        context.prec = max(28, len(number) + len(str(multiplier)) + 2)
        value = _whole(Decimal(number) * multiplier)
    operator = "<=" if role == "LOOKBACK_WINDOW" else _OP[match["op"]]
    return SourceOperand(role, operator, value, unit, source_candidate_id, start_offset,
                         end_offset, quote, tax_basis, anchor)
