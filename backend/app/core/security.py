from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.config import Settings, get_settings
from app.domain.models import User, UserSession
from app.repositories.user_sessions import UserSessionRepository

SESSION_COOKIE = "tdm_session"
CSRF_COOKIE = "tdm_csrf"
CSRF_HEADER = "X-CSRF-Token"
LAST_USED_TOUCH_SECONDS = 3600


async def require_api_token(x_api_token: str | None = Header(default=None)) -> None:
    """Deprecated compatibility helper for the old API-token routes.

    Session auth replaces this mechanism, but the legacy routes still import it
    until they are re-scoped. It remains a no-op when API_TOKEN is unset.
    """
    expected = get_settings().api_token
    if not expected:
        return
    if x_api_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_auth_session(
    session: AsyncSession,
    user_id: int,
    ttl_days: int,
) -> tuple[str, str, UserSession]:
    now = datetime.now(timezone.utc)
    session_token = new_opaque_token()
    csrf_token = new_opaque_token()
    row = await UserSessionRepository(session).create(
        user_id=user_id,
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=now + timedelta(days=ttl_days),
        now=now,
    )
    return session_token, csrf_token, row


def _effective_scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip().lower()
    return request.url.scheme.lower()


def _cookie_secure(request: Request, settings: Settings) -> bool:
    value = (settings.session_cookie_secure or "auto").strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    return _effective_scheme(request) == "https"


def set_auth_cookies(
    response: Response,
    request: Request,
    session_token: str,
    csrf_token: str,
    max_age: int,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    secure = _cookie_secure(request, settings)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        path="/",
        httponly=False,
        samesite="lax",
        secure=secure,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="lax")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def get_optional_user(request: Request, session: AsyncSession) -> User | None:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        return None

    repo = UserSessionRepository(session)
    row = await repo.get_by_token_hash(hash_token(raw_token))
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    if _aware(row.expires_at) <= now:
        await repo.delete_by_token_hash(row.token_hash)
        await session.commit()
        return None

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None

    if _aware(row.last_used_at) + timedelta(seconds=LAST_USED_TOUCH_SECONDS) <= now:
        await repo.touch(row, now)
        await session.commit()

    return user


async def get_current_user(request: Request, session: AsyncSession) -> User:
    user = await get_optional_user(request, session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_admin(user: User) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
