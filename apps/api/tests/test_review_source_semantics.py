"""실제 새 모듈과 1~3단계 모듈을 사용한다. 외부 모델 호출만 대역으로 주입한다."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import types

import pytest

_PACKAGE = "_qualification_reliability_step4"
if _PACKAGE not in sys.modules:
    package = types.ModuleType(_PACKAGE)
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "app/ai/qualification/extraction")]
    sys.modules[_PACKAGE] = package
G = importlib.import_module(f"{_PACKAGE}.review_grounding")
O = importlib.import_module(f"{_PACKAGE}.review_operands")
P = importlib.import_module(f"{_PACKAGE}.review_plan")
E = importlib.import_module(f"{_PACKAGE}.review_execution")


@pytest.mark.parametrize(("source", "quote", "restored", "method"), [
    ("원문 2개 이상 보유", "2개 이상", "2개 이상", "EXACT"),
    ("원문 2개 이상 보유", "2개이상", "2개 이상", "NORMALIZED"),
    ("각 단체급식소※(800식 이상)", "각 단체급식소(800식이상)", "각 단체급식소※(800식 이상)", "NORMALIZED"),
    ("㈜ 테스트 등록", "(주)테스트", "㈜ 테스트", "NORMALIZED"),
    ("수집․운반업（１２２７） 등록", "수집·운반업(1227)", "수집․운반업（１２２７）", "NORMALIZED"),
    ("A\r\n  B 항목", "AB", "A\r\n  B", "NORMALIZED"),
    ("😀 \t조건 유지", "😀조건", "😀 \t조건", "NORMALIZED"),
    ("조항: 1,300,000원 이상", "1,300,000원 이상", "1,300,000원 이상", "EXACT"),
    ("원문 \u1100\u1161 근거", "\u1100\u1161", "\u1100\u1161", "EXACT"),
])
def test_source_slice_roundtrip(source, quote, restored, method):
    result = G.resolve_source_quote(source, quote, base_offset=9)
    assert result.quote == restored and result.method == method
    assert source[result.start_offset - 9:result.end_offset - 9] == result.quote


@pytest.mark.parametrize(("source", "quote", "code"), [
    ("A 조건 B 조건", "조건", "AMBIGUOUS_SOURCE_QUOTE"),
    ("2개 이상 또는 2개이상", "2개\t이상", "AMBIGUOUS_SOURCE_QUOTE"),
    ("12년 이상", "2년 이상", "PARTIAL_NUMERIC_EXPRESSION"),
    ("1.3억원 이상", "3억원 이상", "PARTIAL_NUMERIC_EXPRESSION"),
    ("1억5천만원 이상", "5천만원 이상", "PARTIAL_NUMERIC_EXPRESSION"),
    ("14501 등록", "1450", "PARTIAL_NUMERIC_EXPRESSION"),
    ("-5억원 이상", "5억원 이상", "PARTIAL_NUMERIC_EXPRESSION"),
    ("㈜ 업체", "주", "PARTIAL_NORMALIZED_CHARACTER"),
    ("가 원문", "없는 문장", "QUOTE_NOT_IN_SOURCE"),
    ("최근 2년 내에 그리고 1년 이상", "최근2년;1년이상", "QUOTE_NOT_IN_SOURCE"),
    ("1,300원", "1300원", "QUOTE_NOT_IN_SOURCE"),
    ("5억원 미만", "5억원 이상", "QUOTE_NOT_IN_SOURCE"),
    ("A/B 등록", "AB등록", "QUOTE_NOT_IN_SOURCE"),
    ("원문 \u1100\u1161 근거", "가", "UNSUPPORTED_SOURCE_NORMALIZATION"),
    ("원문 ※ 참고", "※", "EMPTY_SOURCE_QUOTE"),
])
def test_unsafe_restoration_is_rejected(source, quote, code):
    with pytest.raises(G.SourceQuoteError, match=f"^{code}$"):
        G.resolve_source_quote(source, quote)


@pytest.mark.parametrize("offset", [None, -1, True, 1.2])
def test_offset_validation(offset):
    with pytest.raises(G.SourceQuoteError):
        G.resolve_source_quote("abc", "a", base_offset=offset)


@pytest.mark.parametrize("quote", [None, "", " \t"])
def test_empty_quote(quote):
    with pytest.raises(G.SourceQuoteError):
        G.resolve_source_quote("abc", quote)


def parse(role, quote, **kw):
    return O.parse_source_operand(role=role, quote=quote, source_candidate_id="C1",
                                  start_offset=10, end_offset=10 + len(quote), **kw)


@pytest.mark.parametrize(("role", "quote", "value", "unit", "op"), [
    ("LOOKBACK_WINDOW", "최근 2년 이내", 24, "MONTH", "<="),
    ("OPERATION_DURATION", "1년 이상", 12, "MONTH", ">="),
    ("OPERATION_DURATION", "18개월 초과", 18, "MONTH", ">"),
    ("OPERATION_DURATION", "1.5년 이상", 18, "MONTH", ">="),
    ("PERFORMANCE_AMOUNT", "5천만원 이상", 50_000_000, "KRW", ">="),
    ("PERFORMANCE_AMOUNT", "1.3억원 이상", 130_000_000, "KRW", ">="),
    ("PERFORMANCE_AMOUNT", "50,000,000원 미만", 50_000_000, "KRW", "<"),
    ("PERFORMANCE_AMOUNT", "２억원 이상", 200_000_000, "KRW", ">="),
    ("PERFORMANCE_COUNT", "2개 이상", 2, "COUNT", ">="),
    ("PERFORMANCE_COUNT", "1건 초과", 1, "COUNT", ">"),
    ("STAFF_COUNT", "5명 이하", 5, "PERSON", "<="),
    ("DAILY_VOLUME", "1일 평균 800식 이상", 800, "MEAL_PER_DAY", ">="),
    ("BUDGET_AMOUNT", "5억원 이상", 500_000_000, "KRW", ">="),
])
def test_role_specific_operands(role, quote, value, unit, op):
    item = parse(role, quote)
    assert (item.value, item.unit, item.operator) == (value, unit, op)
    assert item.quote == quote and item.role == role


def test_period_roles_are_not_collapsed():
    window = parse("LOOKBACK_WINDOW", "최근 2년 이내", anchor="NOTICE_DATE")
    duration = parse("OPERATION_DURATION", "1년 이상")
    assert window.semantic_payload() != duration.semantic_payload()
    assert window.anchor == "NOTICE_DATE" and duration.anchor is None


def test_budget_and_performance_amount_are_distinct():
    a = parse("PERFORMANCE_AMOUNT", "5억원 이상")
    b = parse("BUDGET_AMOUNT", "5억원 이상")
    assert a.value == b.value and a.semantic_payload() != b.semantic_payload()


@pytest.mark.parametrize(("quote", "tax"), [
    ("2억원(부가세 포함) 이상", "INCLUDED"),
    ("1.3억원 이상 (부가가치세 별도)", "EXCLUDED"),
    ("1.3억원(부가세 제외)이상", "EXCLUDED"),
    ("2억원 이상", "UNSPECIFIED"),
])
def test_tax_is_only_taken_from_the_source(quote, tax):
    assert parse("PERFORMANCE_AMOUNT", quote).tax_basis == tax


@pytest.mark.parametrize(("role", "quote"), [
    ("LOOKBACK_WINDOW", "최근 2년 이내;1년 이상"),
    ("LOOKBACK_WINDOW", "1년 이상"),
    ("OPERATION_DURATION", "최근 2년 이내"),
    ("PERFORMANCE_AMOUNT", "5,00원 이상"),
    ("PERFORMANCE_AMOUNT", "1억 3천만원 이상"),
    ("PERFORMANCE_AMOUNT", "약 5억원 이상"),
    ("PERFORMANCE_AMOUNT", "5억원"),
    ("PERFORMANCE_AMOUNT", "5억원 이상 또는 3억원 이상"),
    ("PERFORMANCE_AMOUNT", "5억원 이상(부가세 포함)(부가세 제외)"),
    ("PERFORMANCE_COUNT", "1.5건 이상"),
    ("STAFF_COUNT", "5건 이상"),
    ("DAILY_VOLUME", "800식 이상"),
])
def test_ambiguous_or_multiple_operands_are_not_guessed(role, quote):
    with pytest.raises(O.OperandError):
        parse(role, quote)


def test_unknown_anchor_is_not_guessed():
    assert parse("LOOKBACK_WINDOW", "최근 3년").anchor is None
    with pytest.raises(O.OperandError):
        parse("LOOKBACK_WINDOW", "최근 3년", anchor="TODAY")
    with pytest.raises(O.OperandError):
        parse("OPERATION_DURATION", "1년 이상", anchor="NOTICE_DATE")


def inventory(text, *, other=None):
    blocks = [{"document_id": "D1", "block_index": 0, "text": text}]
    if other is not None:
        blocks.append({"document_id": "D2", "block_index": 0, "text": other})
    return P.build_review_inventory(blocks, notice_version_id="V1")


def requirement(key, quote, sid=None, name="건수_raw"):
    return {"candidate_id": key, "status": "REQUIREMENT", "reason": None,
            "slots": [{"type": "실적요건", "basis": "SELF_CONTAINED",
                       "fields": [{"name": name, "source_candidate_id": sid or key, "quote": quote}]}]}


def test_normalization_is_connected_to_real_review_executor():
    inv = inventory("가. 2개 이상 실적 보유")
    plan = P.plan_review_requests(inv)
    key = inv.candidates[0].candidate_id
    result = E.execute_review_plan(plan, structured_extract=lambda *args: {"decisions": [requirement(key, "2개이상")]})
    assert result.coverage.coverage_status == "COMPLETE"
    field = result.decisions[0].slots[0].fields[0]
    assert field.quote == "2개 이상" and field.match_method == "NORMALIZED"
    assert inv.candidates[0].text[field.start_offset:field.end_offset] == field.quote
    audit = result.audit()
    assert audit["grounding_version"] == G.GROUNDING_VERSION
    assert "2개 이상" not in json.dumps(audit, ensure_ascii=False)


def test_allowed_context_is_not_the_entire_request():
    inv = inventory("1. 참가자격\n가. 실적 2개 이상\n2. 사업 예산\n가. 5억원 이상")
    plan = P.plan_review_requests(inv, max_targets_per_request=6, neighbor_radius=0)
    target = next(c for c in inv.candidates if "실적" in c.text)
    wrong = next(c for c in inv.candidates if "5억원" in c.text)
    def model(prompt, body, schema):
        payload = json.loads(body)
        return {"decisions": [requirement(key, "5억원 이상", wrong.candidate_id, "금액_raw") if key == target.candidate_id
            else {"candidate_id": key, "status": "NOT_REQUIREMENT", "reason": "테스트상 비대상", "slots": []}
            for key in payload["target_candidate_ids"]]}
    result = E.execute_review_plan(plan, structured_extract=model)
    assert target.candidate_id in result.invalid_candidate_ids
    assert any(item["code"] == "UNRELATED_SOURCE" for event in result.events for item in event.get("rejected", []))


def test_normalized_quote_does_not_allow_foreign_document():
    inv = inventory("실적 필수", other="2개 이상 실적")
    target, other = inv.candidates
    plan = P.plan_review_requests(inv, target_candidate_ids=[target.candidate_id])
    result = E.execute_review_plan(plan, structured_extract=lambda *args: {"decisions": [requirement(target.candidate_id, "2개이상", other.candidate_id)]})
    assert result.coverage.coverage_status == "INVALID"


def test_same_actual_slot_with_different_model_format_is_still_duplicate():
    inv = inventory("2개 이상 실적")
    key = inv.candidates[0].candidate_id
    row = requirement(key, "2개 이상")
    row["slots"].extend(requirement(key, "2개이상")["slots"])
    result = E.execute_review_plan(P.plan_review_requests(inv), structured_extract=lambda *args: {"decisions": [row]})
    assert result.events[0]["rejected"][0]["code"] == "DUPLICATE_SLOT"
    assert not result.decisions


def test_missing_only_retry_still_preserves_normalized_results():
    inv = inventory("가. 2개 이상\n나. 3개 이상")
    a, b = inv.candidates
    calls = []
    def model(prompt, body, schema):
        payload = json.loads(body)
        calls.append(payload["target_candidate_ids"])
        key, quote = (a.candidate_id, "2개이상") if len(calls) == 1 else (b.candidate_id, "3개이상")
        return {"decisions": [requirement(key, quote)]}
    result = E.execute_review_plan(P.plan_review_requests(inv), structured_extract=model)
    assert calls[1] == [b.candidate_id] and result.calls == 2
    assert result.coverage.coverage_status == "COMPLETE"
    assert [d.slots[0].fields[0].quote for d in result.decisions] == ["2개 이상", "3개 이상"]


def test_ambiguous_quote_is_not_retried_to_pick_a_favorable_answer():
    inv = inventory("2개 이상 및 2개이상")
    key = inv.candidates[0].candidate_id
    result = E.execute_review_plan(P.plan_review_requests(inv), structured_extract=lambda *args: {"decisions": [requirement(key, "2개\t이상")]})
    assert result.calls == 1 and result.coverage.coverage_status == "INVALID"
    assert result.events[0]["rejected"][0]["code"] == "AMBIGUOUS_SOURCE_QUOTE"


def test_large_amount_is_not_rounded_by_decimal_context():
    amount = 123456789012345678901234567891
    assert parse("PERFORMANCE_AMOUNT", f"{amount}원 이상").value == amount
