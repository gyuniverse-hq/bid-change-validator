from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.database import SessionLocal
from apps.api.app.main import app
from apps.api.app.models import BidNotice
from apps.api.app.schemas import BusinessType
from apps.api.app.services.notices import save_notice_snapshot


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")
client = TestClient(app)


def _notice_item(notice_no: str) -> dict:
    return {
        "bidNtceNo": notice_no,
        "bidNtceOrd": "00",
        "bidNtceNm": "계약조항 API 테스트 공고",
        "reNtceYn": "N",
        "bidNtceDt": "2026-09-10 09:00:00",
        "bidClseDt": "2026-09-20 10:00:00",
        "ntceInsttCd": "1234567",
        "ntceInsttNm": "테스트기관",
        "dminsttCd": "7654321",
        "dminsttNm": "테스트수요기관",
        "asignBdgtAmt": "100000000",
    }


def test_contract_clause_review_can_be_saved_and_read() -> None:
    db = SessionLocal()
    notice_id = None
    try:
        _, notice, version = save_notice_snapshot(
            db,
            item=_notice_item(f"TEST-CLAUSE-{uuid4()}"),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        notice_id = notice.id

        response = client.post(
            f"/api/v1/notices/{notice.id}/versions/1/contract-clause-reviews",
            json={
                "status": "SUCCEEDED",
                "findings": [
                    {
                        "rule_id": "open_ended_scope",
                        "risk_type": "SCOPE_AMBIGUITY",
                        "label": "과업범위 모호(포괄조항)",
                        "detection_method": "PATTERN_MATCH",
                        "matched_via": "REGEX",
                        "verdict": "NEEDS_REVIEW",
                        "reason": "발주기관 재량으로 범위가 열려 있습니다.",
                        "form": "재량주체+필요인정",
                        "matched_text": "발주기관이 필요하다고 인정하는 업무",
                        "notice_version_id": str(version.id),
                        "chunk_id": "chunk-1",
                        "clause_label": "제5조",
                        "excerpt": "기타 발주기관이 필요하다고 인정하는 업무를 수행합니다.",
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["notice_version_id"] == str(version.id)
        assert body["findings"][0]["category"] == "SCOPE_AMBIGUITY"
        assert body["findings"][0]["risk_type"] == "과업범위 모호"
        assert body["findings"][0]["verdict"] == "확인 필요"

        listed = client.get(
            f"/api/v1/notices/{notice.id}/versions/1/contract-clause-reviews"
        )
        assert listed.status_code == 200
        assert listed.json()[0]["finding_count"] == 1
        assert listed.json()[0]["needs_review_count"] == 1

        detail = client.get(f"/api/v1/contract-clause-reviews/{body['id']}")
        assert detail.status_code == 200
        assert detail.json() == body
    finally:
        if notice_id is not None:
            persisted = db.get(BidNotice, notice_id)
            if persisted is not None:
                db.delete(persisted)
                db.commit()
        db.close()


def test_contract_clause_review_rejects_mismatched_version() -> None:
    db = SessionLocal()
    notice_id = None
    try:
        _, notice, _ = save_notice_snapshot(
            db,
            item=_notice_item(f"TEST-CLAUSE-MISMATCH-{uuid4()}"),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        notice_id = notice.id

        response = client.post(
            f"/api/v1/notices/{notice.id}/versions/1/contract-clause-reviews",
            json={
                "findings": [
                    {
                        "rule_id": "open_ended_scope",
                        "risk_type": "SCOPE_AMBIGUITY",
                        "label": "과업범위 모호",
                        "detection_method": "PATTERN_MATCH",
                        "verdict": "NEEDS_REVIEW",
                        "reason": "확인 필요",
                        "notice_version_id": str(uuid4()),
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CLAUSE_FINDING_VERSION_MISMATCH"
    finally:
        if notice_id is not None:
            persisted = db.get(BidNotice, notice_id)
            if persisted is not None:
                db.delete(persisted)
                db.commit()
        db.close()
