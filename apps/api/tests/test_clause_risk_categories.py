from apps.api.app.ai.clause_review import (
    ClauseFinding,
    apply_overlapping_categories,
    overlapping_categories,
)
from apps.api.app.ai.demo.web import _finding_json


def _finding(
    rule_id: str, label: str, excerpt: str, verdict: str = "NEEDS_REVIEW"
) -> ClauseFinding:
    return ClauseFinding(
        rule_id=rule_id,
        risk_type=None,
        label=label,
        detection_method="STANDARD_DIFF",
        verdict=verdict,
        reason="검토 필요",
        notice_version_id="version-1",
        chunk_id="CHUNK-0001",
        clause_label="6.1",
        excerpt=excerpt,
    )


def test_overlapping_clause_keeps_every_risk_type_and_category() -> None:
    sentence = "지체상금은 1일당 0.5%이며 총액은 계약금액의 30%를 한도로 한다."
    cap = _finding("penalty_cap", "지체상금 상한 초과", sentence)
    rate = _finding("penalty_rate", "지체상금 요율 과다", sentence)

    risk_types, categories = overlapping_categories(cap, [cap, rate])
    payload = _finding_json(cap, [cap, rate])

    assert risk_types == ["LATE_PENALTY", "LATE_PENALTY_RATE"]
    assert categories == ["지체상금 상한", "지체상금 요율"]
    assert payload["risk_type"] == "LATE_PENALTY"
    assert payload["risk_types"] == risk_types
    assert payload["category"] == "지체상금 상한"
    assert payload["categories"] == categories

    rate_payload = _finding_json(rate, [cap, rate])
    assert rate_payload["risk_type"] == "LATE_PENALTY"
    assert rate_payload["category"] == "지체상금 상한"
    assert rate_payload["categories"] == ["지체상금 상한", "지체상금 요율"]


def test_actionable_verdict_wins_before_the_canonical_type_order() -> None:
    sentence = "지체상금은 1일당 0.5%이며 총액은 계약금액의 30%를 한도로 한다."
    compliant_cap = _finding(
        "penalty_cap", "지체상금 상한", sentence, verdict="COMPLIANT"
    )
    risky_rate = _finding(
        "penalty_rate", "지체상금 요율 과다", sentence, verdict="NEEDS_REVIEW"
    )

    payload = _finding_json(compliant_cap, [compliant_cap, risky_rate])

    assert payload["risk_type"] == "LATE_PENALTY_RATE"
    assert payload["category"] == "지체상금 요율"
    assert payload["categories"] == ["지체상금 요율", "지체상금 상한"]


def test_different_source_text_in_same_chunk_is_not_merged() -> None:
    payment = _finding("payment_period", "대금지급 기한 과다", "대금은 30일 이내 지급한다.")
    liability = _finding("liability_scope", "손해배상 범위 과다", "모든 손해를 배상한다.")

    risk_types, categories = overlapping_categories(payment, [payment, liability])

    assert risk_types == ["PAYMENT_TERMS"]
    assert categories == ["대금지급"]

    stored = apply_overlapping_categories([payment])[0].model_dump()
    assert stored["risk_type"] == "PAYMENT_TERMS"
    assert stored["risk_types"] == ["PAYMENT_TERMS"]
    assert stored["category"] == "대금지급"
    assert stored["categories"] == ["대금지급"]


def test_unmapped_internal_rule_still_has_a_non_empty_category_list() -> None:
    finding = _finding(
        "warranty_bond_rate", "하자보수보증금율", "하자보수보증금율은 2%로 한다."
    )

    payload = _finding_json(finding, [finding])
    stored = apply_overlapping_categories([finding])[0].model_dump()

    assert payload["risk_type"] is None
    assert payload["category"] == "하자보수보증금율"
    assert payload["categories"] == ["하자보수보증금율"]
    assert stored["categories"] == ["하자보수보증금율"]
