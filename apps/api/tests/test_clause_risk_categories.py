from apps.api.app.ai.clause_review import (
    CATEGORY_BY_RULE,
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
        risk_type=label,
        category=CATEGORY_BY_RULE[rule_id],
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

    categories, risk_types = overlapping_categories(cap, [cap, rate])
    payload = _finding_json(cap, [cap, rate])

    assert categories == ["LATE_PENALTY", "LATE_PENALTY_RATE"]
    assert risk_types == ["지체상금 상한 초과", "지체상금 요율 과다"]
    assert payload["risk_type"] == "지체상금 상한 초과"
    assert payload["risk_types"] == risk_types
    assert payload["category"] == "LATE_PENALTY"
    assert payload["categories"] == categories

    rate_payload = _finding_json(rate, [cap, rate])
    assert rate_payload["risk_type"] == "지체상금 상한 초과"
    assert rate_payload["category"] == "LATE_PENALTY"
    assert rate_payload["categories"] == ["LATE_PENALTY", "LATE_PENALTY_RATE"]


def test_actionable_verdict_wins_before_the_canonical_type_order() -> None:
    sentence = "지체상금은 1일당 0.5%이며 총액은 계약금액의 30%를 한도로 한다."
    compliant_cap = _finding(
        "penalty_cap", "지체상금 상한", sentence, verdict="COMPLIANT"
    )
    risky_rate = _finding(
        "penalty_rate", "지체상금 요율 과다", sentence, verdict="NEEDS_REVIEW"
    )

    payload = _finding_json(compliant_cap, [compliant_cap, risky_rate])

    assert payload["risk_type"] == "지체상금 요율 과다"
    assert payload["category"] == "LATE_PENALTY_RATE"
    assert payload["categories"] == ["LATE_PENALTY_RATE", "LATE_PENALTY"]


def test_different_source_text_in_same_chunk_is_not_merged() -> None:
    payment = _finding("payment_period", "대금지급 기한 과다", "대금은 30일 이내 지급한다.")
    liability = _finding("liability_scope", "손해배상 범위 과다", "모든 손해를 배상한다.")

    categories, risk_types = overlapping_categories(payment, [payment, liability])

    assert categories == ["PAYMENT_TERMS"]
    assert risk_types == ["대금지급 기한 과다"]

    stored = apply_overlapping_categories([payment])[0].model_dump()
    assert stored["risk_type"] == "대금지급 기한 과다"
    assert stored["risk_types"] == ["대금지급 기한 과다"]
    assert stored["category"] == "PAYMENT_TERMS"
    assert stored["categories"] == ["PAYMENT_TERMS"]


def test_warranty_bond_rule_uses_warranty_category_and_its_own_label() -> None:
    finding = _finding(
        "warranty_bond_rate", "하자보수보증금율", "하자보수보증금율은 2%로 한다."
    )

    payload = _finding_json(finding, [finding])
    stored = apply_overlapping_categories([finding])[0].model_dump()

    assert payload["risk_type"] == "하자보수보증금율"
    assert payload["risk_types"] == ["하자보수보증금율"]
    assert payload["category"] == "WARRANTY_PERIOD"
    assert payload["categories"] == ["WARRANTY_PERIOD"]
    assert stored["categories"] == ["WARRANTY_PERIOD"]


def test_multiple_korean_labels_are_kept_when_they_share_one_category() -> None:
    sentence = "하자보수 기간은 3년이며 하자보수보증금율은 2%로 한다."
    period = _finding("warranty_period", "하자보수 기간 과다", sentence)
    bond = _finding("warranty_bond_rate", "하자보수보증금율 과다", sentence)

    payload = _finding_json(period, [period, bond])

    assert payload["category"] == "WARRANTY_PERIOD"
    assert payload["categories"] == ["WARRANTY_PERIOD"]
    assert payload["risk_type"] == "하자보수 기간 과다"
    assert payload["risk_types"] == ["하자보수 기간 과다", "하자보수보증금율 과다"]
