"""분리 로더가 아니라 실제 앱 조립·ORM 등록을 검증하는 회귀 테스트.

GET 문서 스키마와 mapper 구성만 확인한다. 실제 공고 추출/원격 서비스 검증은 아니다.
"""
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import configure_mappers

from apps.api.app.main import app
from apps.api.app.qualification.routers import catalog, state


def test_state_and_catalog_registered_once_in_real_app():
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    for path in ("/api/v1/preflight-cases/{case_id}/qualification-state",
                 "/api/v1/qualification-notice-catalog"):
        found = [route for route in routes if route.path == path and "GET" in route.methods]
        assert len(found) == 1
    # 독립 state 모듈이 catalog를 암묵적으로 포함하지 않아야 한다.
    assert not any(route.path == "/qualification-notice-catalog" for route in state.router.routes)
    assert any(route.path == "/qualification-notice-catalog" for route in catalog.router.routes)


def test_real_openapi_and_mappers_include_new_read_paths():
    configure_mappers()
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "get" in paths["/api/v1/preflight-cases/{case_id}/qualification-state"]
    assert "get" in paths["/api/v1/qualification-notice-catalog"]
    assert not any("/api/v1/api/v1/" in path for path in paths)
