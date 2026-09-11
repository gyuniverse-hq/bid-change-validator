"""HTTP endpoints for login, current-user lookup, and logout."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..auth import get_current_session, get_current_user, login, revoke_session
from ..auth_models import AppUser, AuthSession
from ..auth_schemas import AuthUserRead, LoginRequest, LoginResponse
from ..config import get_settings
from ..database import get_db


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _user_response(user: AppUser) -> AuthUserRead:
    return AuthUserRead(id=user.id, username=user.username, role=user.role)


@router.post("/login", response_model=LoginResponse)
def login_user(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    raw_token, session = login(
        db, username=payload.username, password=payload.password
    )
    settings = get_settings()
    response.set_cookie(
        key="bidcheck_session",
        value=raw_token,
        httponly=True,
        secure=settings.auth_cookie_secure or settings.app_environment == "production",
        samesite="lax",
        max_age=settings.auth_session_ttl_hours * 3600,
        path="/",
    )
    return LoginResponse(
        access_token=raw_token,
        expires_at=session.expires_at,
        user=_user_response(session.user),
    )


@router.get("/me", response_model=AuthUserRead)
def current_user(user: AppUser = Depends(get_current_user)) -> AuthUserRead:
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(
    response: Response,
    session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    revoke_session(db, session)
    response.delete_cookie("bidcheck_session", path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
