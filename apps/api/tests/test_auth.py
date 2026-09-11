import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.auth_models import AppUser, AuthSession
from apps.api.app import auth as auth_service
from apps.api.app.config import get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.main import app


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")


def test_development_admin_login_session_and_logout() -> None:
    client = TestClient(app)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"},
    )

    assert login_response.status_code == 200, login_response.text
    body = login_response.json()
    token = body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "ADMIN"
    assert "HttpOnly" in login_response.headers["set-cookie"]

    db = SessionLocal()
    try:
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash
                == hashlib.sha256(token.encode("utf-8")).hexdigest()
            )
        )
        assert session is not None
        assert session.token_hash != token
    finally:
        db.close()

    me_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"

    logout_response = client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert logout_response.status_code == 204
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )

    db = SessionLocal()
    try:
        user = db.scalar(select(AppUser).where(AppUser.username == "admin"))
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.close()


def test_invalid_login_does_not_reveal_which_credential_failed() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "not-the-password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_business_apis_require_session_when_enabled(monkeypatch) -> None:
    protected_settings = get_settings().model_copy(update={"auth_required": True})
    monkeypatch.setattr(auth_service, "get_settings", lambda: protected_settings)
    protected_client = TestClient(app)

    unauthorized = protected_client.get("/api/v1/companies")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert protected_client.get("/health").status_code == 200

    login_response = protected_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    authorized = protected_client.get(
        "/api/v1/companies",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert authorized.status_code == 200

    db = SessionLocal()
    try:
        user = db.scalar(select(AppUser).where(AppUser.username == "admin"))
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.close()
