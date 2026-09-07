import pytest

from apps.api.app.ai.clause_review import detect_standard_diff
from apps.api.app.ai.clause_review.standards import resolve_all, split_clauses


# A trimmed stand-in for 용역계약일반조건. Every threshold the rules compare against
# is read out of this text, so the tests exercise the real extraction path rather
# than constants written into the test.
STANDARD_TEXT = """제2장 계약의 이행

제18조(지체상금)
①계약담당공무원은 계약상대자가 계약의 이행을 지체한 때에는 지체상금을 부과하여야 한다. 다만, 지체상금의 총액이 계약금액의 100분의 30을 초과하는 경우에는 100분의 30으로 한다.

제20조(검사)
②계약담당공무원은 제1항의 통지를 받은 날부터 14일 이내에 그 검사를 완료하여야 한다.

제31조(계약의 해제·해지)
①계약상대자는 다음 각 호의 어느 하나에 해당하는 경우 계약을 해제 또는 해지할 수 있다.
1. 계약금액이 100분의 40이상 감소되었을 때

제4장 계약의 종료

제56조(지식재산권의 귀속)
①이 계약에 의하여 작성된 산출물에 대한 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며, 특약이 없으면 지분은 균등한 것으로 한다.

제58조(하자보수)
①계약상대자는 사업의 종료를 확인한 후 1년간 발생한 하자에 대하여 보수책임이 있다.

제59조(하자보수보증금)
①계약상대자는 하자보수보증금율(100분의 2, 장기계속계약의 경우에는 연차별로 산정한다)에 해당하는 금액을 납부하여야 한다.
"""


@pytest.fixture(scope="module")
def clauses() -> list[dict]:
    return split_clauses("용역계약일반조건", STANDARD_TEXT)


def _chunk(text: str, chunk_id: str = "CHUNK-0001", clause_label: str | None = "5.1") -> dict:
    return {"chunk_id": chunk_id, "clause_label": clause_label, "text": text}


def _by_rule(findings) -> dict:
    return {finding.rule_id: finding for finding in findings}


# ── the thresholds come from the rule text, not from code ────────────────
def test_every_threshold_is_read_out_of_the_standard_text(clauses) -> None:
    resolved = resolve_all(clauses)

    assert {rule_id: item["status"] for rule_id, item in resolved.items()} == {
        "warranty_period": "ok",
        "warranty_bond_rate": "ok",
        "penalty_cap": "ok",
        "inspection_period": "ok",
        "termination_threshold": "ok",
        "ip_ownership": "ok",
    }
    assert resolved["warranty_period"]["value"] == 12
    assert resolved["warranty_period"]["raw"] == "1년"
    assert resolved["penalty_cap"]["value"] == 30
    assert resolved["warranty_bond_rate"]["value"] == 2
    assert resolved["termination_threshold"]["value"] == 40
    # No drift: the extracted values match what the specs recorded.
    assert all(item["drift"] is None for item in resolved.values())


def test_an_amended_threshold_is_used_and_flagged_as_drift() -> None:
    amended = split_clauses(
        "용역계약일반조건",
        "제58조(하자보수)\n①계약상대자는 사업의 종료를 확인한 후 2년간 발생한 하자에 대하여 보수책임이 있다.\n",
    )
    resolved = resolve_all(amended)["warranty_period"]

    # The rule text wins; the mismatch with the recorded value is reported.
    assert resolved["value"] == 24
    assert resolved["drift"] == {"recorded": 12, "extracted": 24}
    assert "개정" in resolved["notes"]

    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 인수 확인 후 18개월간 하자보수 책임을 진다.")], amended
        )
    )
    # 18 months is over the standard 12 but within an amended 24.
    assert findings["warranty_period"].verdict == "COMPLIANT"


def test_a_missing_standard_clause_withholds_the_verdict(clauses) -> None:
    without_warranty = [item for item in clauses if item["clause_no"] != "58조"]

    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 하자담보책임기간은 인수일로부터 36개월로 한다.")], without_warranty
        )
    )

    finding = findings["warranty_period"]
    assert finding.verdict == "UNDETERMINED"
    assert finding.matched_via == "STANDARD_UNRESOLVED"
    assert "판정 보류" in finding.reason


# ── numeric comparison ───────────────────────────────────────────────────
def test_a_warranty_period_over_the_standard_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 인수 확인 후 36개월간 하자보수 책임을 진다.")], clauses
        )
    )

    finding = findings["warranty_period"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.notice_value == 36
    assert finding.standard is not None
    assert finding.standard.value == 12
    assert finding.standard.clause_ref == "용역계약일반조건 제58조제1항"
    # The excerpt of the standard clause travels with the finding as its ground.
    assert finding.standard.text_excerpt


def test_a_warranty_period_within_the_standard_is_compliant(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 인수 확인 후 12개월간 하자보수 책임을 진다.")], clauses
        )
    )

    assert findings["warranty_period"].verdict == "COMPLIANT"


def test_a_penalty_cap_over_the_standard_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("6.1 지체상금의 총액은 계약금액의 100분의 50을 한도로 한다.")], clauses
        )
    )

    finding = findings["penalty_cap"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.notice_value == 50


def test_the_daily_penalty_rate_is_not_compared_against_the_cap(clauses) -> None:
    # 0.5% is the per-day rate, not a cap. Comparing it would report every notice
    # as compliant on a number that has nothing to do with the standard.
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "6.1 지체상금은 지연일수 1일당 계약금액의 0.5%로 하며, "
                    "그 총액은 계약금액의 100분의 30을 초과하지 아니한다."
                )
            ],
            clauses,
        )
    )

    finding = findings["penalty_cap"]
    assert finding.verdict == "COMPLIANT"
    assert finding.notice_value == 30


def test_a_stricter_termination_threshold_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("8.1 계약금액이 100분의 60 이상 감소한 경우에 한하여 계약을 해지할 수 있다.")],
            clauses,
        )
    )

    assert findings["termination_threshold"].verdict == "NEEDS_REVIEW"
    assert findings["termination_threshold"].notice_value == 60


# ── figures must not be attributed to the wrong rule ─────────────────────
def test_a_warranty_figure_is_not_read_as_an_inspection_period(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 하자담보책임기간은 검수완료일로부터 36개월로 한다.")], clauses
        )
    )

    # The warranty rule owns this sentence.
    assert findings["warranty_period"].verdict == "NEEDS_REVIEW"
    assert findings["warranty_period"].notice_value == 36
    # The inspection rule must not claim the same 36 months. The sentence is
    # excluded from it entirely, so it reports nothing rather than a wrong value.
    assert "inspection_period" not in findings


def test_a_bond_rate_figure_is_not_read_as_a_warranty_period(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.2 하자보수보증금은 계약금액의 100분의 10으로 한다.")], clauses
        )
    )

    assert findings["warranty_bond_rate"].verdict == "NEEDS_REVIEW"
    assert findings["warranty_bond_rate"].notice_value == 10
    # The warranty-period rule excludes any sentence mentioning a bond, so the
    # 100분의 10 here can never be read as a warranty duration.
    assert "warranty_period" not in findings


# ── wording comparison ───────────────────────────────────────────────────
def test_sole_vesting_of_intellectual_property_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("9.1 본 용역의 모든 산출물에 대한 저작권은 발주기관에 귀속한다.")], clauses
        )
    )

    finding = findings["ip_ownership"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.matched_text


def test_joint_ownership_wording_matches_the_standard(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "9.1 산출물의 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며 "
                    "지분은 균등한 것으로 한다."
                )
            ],
            clauses,
        )
    )

    assert findings["ip_ownership"].verdict == "COMPLIANT"


def test_a_sole_vesting_sentence_is_still_found_next_to_a_compliant_one(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "9.1 산출물의 지식재산권은 양 당사자가 공동으로 소유한다.\n"
                    "9.2 다만 소프트웨어 저작재산권은 발주기관이 단독 보유한다."
                )
            ],
            clauses,
        )
    )

    # Checking the chunk as a whole would let the compliant sentence hide this.
    assert findings["ip_ownership"].verdict == "NEEDS_REVIEW"


# ── the embedding tier only runs when tier one gave no answer ────────────
def _recording_fallback(verdict=None):
    calls: list[str] = []

    def fallback(rule, resolved, chunks, inspected_ids):
        calls.append(rule["id"])
        if verdict is None:
            return (None, "", None, None, None)
        return (verdict, "임베딩 검색으로 근거 확인", None, "인용문", chunks[0])

    fallback.calls = calls  # type: ignore[attr-defined]
    return fallback


def test_a_confident_regex_verdict_does_not_trigger_the_embedding_tier(clauses) -> None:
    fallback = _recording_fallback()

    detect_standard_diff(
        [_chunk("5.1 계약상대자는 인수 확인 후 36개월간 하자보수 책임을 진다.")],
        clauses,
        embedding_fallback=fallback,
    )

    assert "warranty_period" not in fallback.calls


def test_a_rule_with_no_regex_match_does_trigger_the_embedding_tier(clauses) -> None:
    fallback = _recording_fallback(verdict="NEEDS_REVIEW")

    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 품질을 보장하며 발생하는 문제를 자비로 해결한다.")],
            clauses,
            embedding_fallback=fallback,
        )
    )

    assert "warranty_period" in fallback.calls
    assert findings["warranty_period"].matched_via == "EMBEDDING_LLM"


def test_without_a_fallback_an_unmatched_rule_simply_reports_nothing(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("3.1 시스템 분석 및 설계를 수행한다.")], clauses
        )
    )

    assert "warranty_period" not in findings


def test_findings_carry_the_notice_version(clauses) -> None:
    findings = detect_standard_diff(
        [_chunk("5.1 인수 확인 후 36개월간 하자보수 책임을 진다.")],
        clauses,
        notice_version_id="nv-001",
    )

    assert all(finding.notice_version_id == "nv-001" for finding in findings)
