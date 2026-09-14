"""실제 앱 조립·ORM 등록 검증. 라우팅 내부 구현 대신 HTTP 계약을 확인한다."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import configure_mappers

from apps.api.app.main import app
from apps.api.app.qualification.routers import catalog, state


def test_state_and_catalog_registered_in_real_app():
    # include_router의 내부 자료형 대신 실제 HTTP 매칭/검증 결과를 검사한다.
    with TestClient(app) as client:
        state_response = client.get("/api/v1/preflight-cases/not-a-uuid/qualification-state")
        catalog_response = client.get("/api/v1/qualification-notice-catalog?limit=101")
    assert state_response.status_code == 422, state_response.text
    assert catalog_response.status_code == 422, catalog_response.text
    assert not any(getattr(route, "path", None) == "/qualification-notice-catalog" for route in state.router.routes)
    assert any(getattr(route, "path", None) == "/qualification-notice-catalog" for route in catalog.router.routes)


def test_real_openapi_and_mappers_include_new_read_paths():
    configure_mappers()
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "get" in paths["/api/v1/preflight-cases/{case_id}/qualification-state"]
    assert "get" in paths["/api/v1/qualification-notice-catalog"]
    assert not any("/api/v1/api/v1/" in path for path in paths)
    operation_ids = [value["operationId"] for methods in paths.values() for value in methods.values()
                     if isinstance(value, dict) and "operationId" in value]
    assert len(operation_ids) == len(set(operation_ids))
