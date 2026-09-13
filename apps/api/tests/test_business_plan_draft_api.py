"""프론트가 사건 ID 와 입력만 보내면 판정 결과로 초안이 나오는지 확인한다.

프론트가 막혀 있던 지점이 정확히 이 엔드포인트 하나였다. 생성기·조판기는 각각
검증됐지만, 사건에서 판정 실행을 읽어 둘을 잇는 경로는 없었다. 여기서 밟는 것은
그 경로다 — 판정 결과가 초안에 그대로 실리는가, 그리고 근거를 클라이언트가 만들
필요가 없는가.

모델은 부르지 않는다. 가짜 나레이터가 받은 프롬프트를 돌려주게 해서 **모델이 무엇을
봤는지**를 검증한다. 그것이 이 배선이 책임지는 전부다. 모델이 그 위에서 무엇을 쓰는지는
quality_eval/business_plan 이 288편으로 잰다.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.routers import business_plan_drafts as router_module
from apps.api.tests.test_mvp_golden_e2e import REFERENCE_DATE, _cleanup, _seed_golden_case


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")
client = TestClient(app)


class _EchoNarrator:
    """받은 본문을 초안으로 돌려준다 — 모델이 본 것이 곧 응답이 된다."""

    available = True

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __call__(self, system_prompt: str, body: str) -> str:
        sections = "\n".join(
            f"# {index}. {name}"
            for index, name in enumerate(
                [
                    "사업 이해 및 제안 목표",
                    "추진 전략 및 수행 방안",
                    "조직·인력 및 역할",
                    "일정 및 산출물 계획",
                    "품질·위험 및 계약조건 대응",
                    "자격요건·제출 전 확인사항",
                ],
                start=1,
            )
        )
        return f"{sections}\n\n{body}"


class _NoKeyNarrator(_EchoNarrator):
    available = False


def _judge(seed) -> dict:
    completeness = client.patch(
        f"/api/v1/companies/{seed['company_id']}/qualification-profile-completeness",
        json={"staff_roles": True, "performances": True, "certifications": False},
    )
    assert completeness.status_code == 200, completeness.text
    response = client.post(
        f"/api/v1/preflight-cases/{seed['case_id']}/qualification-judgments",
        json={
            "analysis_run_id": str(seed["baseline_analysis_id"]),
            "reference_date": REFERENCE_DATE,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_draft_is_grounded_in_the_case_judgment_not_in_client_input(monkeypatch) -> None:
    monkeypatch.setattr(router_module, "OpenAINarrator", _EchoNarrator)
    seed = _seed_golden_case()
    try:
        judgment = _judge(seed)
        flagged = [item for item in judgment["judgments"] if item["status"] != "SATISFIED"]
        assert flagged, "시드에 확인 필요 요건이 하나는 있어야 이 테스트가 의미 있다"

        response = client.post(
            f"/api/v1/preflight-cases/{seed['case_id']}/business-plan-draft",
            json={"inputs": {"proposal_goal": "안정적으로 수행하겠습니다."}},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "OK"
        assert body["disclaimer"]
        assert body["source"]["judgment_count"] == len(judgment["judgments"])
        assert body["source"]["flagged_clause_count"] == len(flagged)

        # 모델이 본 것(=에코된 본문)에 판정 결과가 서버 조판 형식으로 들어 있다.
        # 클라이언트는 판정을 보내지 않았다 — 서버가 judgment run 에서 읽은 것이다.
        text = body["text"]
        assert "[참가자격 판정]" in text
        assert "확인 필요" in text
        assert "[사용자 입력]" in text
        assert "안정적으로 수행하겠습니다." in text
        # 요건은 라벨 형식으로 하나도 빠짐없이 들어간다.
        for index in range(1, len(judgment["judgments"]) + 1):
            assert f"- 요건{index} " in text, f"요건{index} 가 브리핑에 없다"
    finally:
        _cleanup(seed)


def test_a_case_without_a_judgment_is_refused_not_drafted(monkeypatch) -> None:
    """판정이 없는데 초안을 쓰면 근거 없는 문서가 나온다. 그건 이 기능의 최악이다."""
    monkeypatch.setattr(router_module, "OpenAINarrator", _EchoNarrator)
    seed = _seed_golden_case()
    try:
        response = client.post(
            f"/api/v1/preflight-cases/{seed['case_id']}/business-plan-draft",
            json={"inputs": {"proposal_goal": "수행합니다"}},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "JUDGMENT_RUN_REQUIRED"
    finally:
        _cleanup(seed)


def test_missing_api_key_is_a_result_not_a_server_error(monkeypatch) -> None:
    """키가 없으면 200 + NARRATOR_UNAVAILABLE. 화면이 '운영에 문의'로 안내할 수 있게."""
    monkeypatch.setattr(router_module, "OpenAINarrator", _NoKeyNarrator)
    seed = _seed_golden_case()
    try:
        _judge(seed)
        response = client.post(
            f"/api/v1/preflight-cases/{seed['case_id']}/business-plan-draft",
            json={"inputs": {"proposal_goal": "수행합니다"}},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "NARRATOR_UNAVAILABLE"
    finally:
        _cleanup(seed)


def test_empty_inputs_are_told_apart_from_a_missing_key(monkeypatch) -> None:
    monkeypatch.setattr(router_module, "OpenAINarrator", _EchoNarrator)
    seed = _seed_golden_case()
    try:
        _judge(seed)
        response = client.post(
            f"/api/v1/preflight-cases/{seed['case_id']}/business-plan-draft",
            json={"inputs": {}},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "EMPTY_INPUT"
    finally:
        _cleanup(seed)


def test_unknown_case_is_a_404() -> None:
    response = client.post(
        f"/api/v1/preflight-cases/{uuid4()}/business-plan-draft",
        json={"inputs": {"proposal_goal": "수행합니다"}},
    )

    assert response.status_code == 404
