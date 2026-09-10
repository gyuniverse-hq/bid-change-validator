from apps.api.app.ai.clause_review import ClauseFinding, overlapping_categories
from apps.api.app.ai.demo_web import _finding_json


def _finding(rule_id: str, label: str, excerpt: str) -> ClauseFinding:
    return ClauseFinding(
        rule_id=rule_id,
        risk_type=label,
        detection_method="STANDARD_DIFF",
        verdict="NEEDS_REVIEW",
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
    assert payload["category"] == "지체상금 상한"
    assert payload["risk_types"] == risk_types
    assert payload["categories"] == categories

    rate_payload = _finding_json(rate, [cap, rate])
    assert rate_payload["risk_type"] == "LATE_PENALTY_RATE"
    assert rate_payload["category"] == "지체상금 요율"
    assert set(rate_payload["risk_types"]) == {"LATE_PENALTY", "LATE_PENALTY_RATE"}


def test_different_source_text_in_same_chunk_is_not_merged() -> None:
    payment = _finding("payment_period", "대금지급 기한 과다", "대금은 30일 이내 지급한다.")
    liability = _finding("liability_scope", "손해배상 범위 과다", "모든 손해를 배상한다.")

    risk_types, categories = overlapping_categories(payment, [payment, liability])

    assert risk_types == ["PAYMENT_TERMS"]
    assert categories == ["대금지급"]
