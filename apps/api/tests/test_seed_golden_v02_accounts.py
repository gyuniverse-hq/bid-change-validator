import json
from pathlib import Path

import pytest

from apps.api.app.scripts.seed_golden_v02_accounts import (
    golden_business_number,
    golden_username,
    load_golden_bundle,
    synthetic_industry_code,
)


def test_golden_account_identifiers_are_stable() -> None:
    assert golden_username("J01") == "golden-j01"
    assert golden_username("J32") == "golden-j32"
    assert golden_business_number("J01") == "9902000001"
    assert golden_business_number("J32") == "9902000032"
    assert synthetic_industry_code("J09", 1) == "GOLDEN-J09-01"


def test_golden_username_rejects_non_product_case() -> None:
    with pytest.raises(ValueError):
        golden_username("CH01-BEFORE")


def test_load_golden_bundle_keeps_current_company_cases(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "fixture_bundle.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "J02"},
                    {"case_id": "CH01-BEFORE"},
                    {"case_id": "J01"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "sources" / "evidence_all.json").write_text(
        json.dumps([{"evidence_id": "E001"}]),
        encoding="utf-8",
    )

    cases, evidence = load_golden_bundle(tmp_path)

    assert [item["case_id"] for item in cases] == ["J01", "J02"]
    assert evidence == {"E001": {"evidence_id": "E001"}}
