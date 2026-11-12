from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import (
    AuthServiceDep,
    CurrentUserDep,
    SessionDep,
    TwitchUserDep,
)
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.exceptions import (
    AuthError,
    NotConfiguredError,
    ProviderError,
)
from app.core.rate_limit import client_ip, get_auth_limiter
from app.core.security import (
    SESSION_COOKIE,
    clear_auth_cookies,
    get_optional_user,
    set_auth_cookies,
)
from app.domain.schemas import (
    AuthConnectIn,
    AuthConnectOut,
    AuthMeOut,
    AuthUserOut,
    RegistrationStateOut,
    TelegramSettingsIn,
    TwitchConnectOut,
)
from app.services.factory import build_progress_service

logger = logging.getLogger(__name__)

router = APIRouter()


_sync_tasks: set[asyncio.Task[None]] = set()


async def _run_first_progress_sync(user_id: int) -> None:
    async with SessionLocal() as session:
        try:
            await build_progress_service(session, user_id).run()
        except (NotConfiguredError, ProviderError):
            logger.info("First progress sync skipped for user %s", user_id)
        except Exception:  # noqa: BLE001 - background best effort  # pragma: no cover
            logger.warning("First progress sync failed for user %s", user_id)


async def _first_progress_sync(user_id: int) -> None:
    """Schedule a best-effort first inventory sync in the background."""
    try:
        task = asyncio.create_task(_run_first_progress_sync(user_id))
    except RuntimeError:  # pragma: no cover - no running loop during shutdown
        return
    _sync_tasks.add(task)
    task.add_done_callback(_sync_tasks.discard)


async def shutdown_first_progress_syncs() -> None:
    """Cancel in-flight first-sync tasks during application shutdown."""
    while _sync_tasks:
        tasks = list(_sync_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    _sync_tasks.clear()


@router.get("/auth/me", response_model=AuthMeOut)
async def auth_me(
    request: Request, session: SessionDep, service: AuthServiceDep
) -> AuthMeOut:
    user = await get_optional_user(request, session)
    state = await service.registration_state()
    settings = get_settings()
    return AuthMeOut(
        authenticated=user is not None,
        user=AuthUserOut.model_validate(user) if user is not None else None,
        registration=RegistrationStateOut(
            open=state.open, invite_required=state.invite_required
        ),
        telegram_bot_configured=bool(settings.telegram_bot_token),
    )


@router.get("/auth/twitch/authorize", response_model=TwitchConnectOut)
async def auth_authorize(provider: TwitchUserDep) -> TwitchConnectOut:
    return TwitchConnectOut(
        authorize_url=provider.authorize_url,
        redirect_uri=provider.settings.twitch_oauth_redirect_uri,
    )


@router.post("/auth/twitch/connect", response_model=AuthConnectOut)
async def auth_connect(
    payload: AuthConnectIn,
    request: Request,
    response: Response,
    session: SessionDep,
    service: AuthServiceDep,
) -> AuthConnectOut:
    limiter = get_auth_limiter()
    key = client_ip(request)
    if not limiter.check(key):
        retry_after = limiter.retry_after(key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )

    current_user = await get_optional_user(request, session)
    try:
        result = await service.connect(
            payload.redirect_url, payload.invite_code, current_user
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    max_age = service.settings.session_ttl_days * 24 * 60 * 60
    set_auth_cookies(
        response,
        request,
        result.session_token,
        result.csrf_token,
        max_age,
        settings=service.settings,
    )
    await _first_progress_sync(result.user.id)

    return AuthConnectOut(
        connected=True,
        user=AuthUserOut.model_validate(result.user),
        created=result.created,
    )


@router.post("/auth/logout")
async def auth_logout(
    request: Request,
    response: Response,
    _user: CurrentUserDep,
    service: AuthServiceDep,
) -> dict:
    await service.logout(request.cookies.get(SESSION_COOKIE))
    clear_auth_cookies(response)
    return {"ok": True}


@router.patch("/auth/me", response_model=AuthUserOut)
async def auth_update_me(
    payload: TelegramSettingsIn,
    user: CurrentUserDep,
    service: AuthServiceDep,
) -> AuthUserOut:
    try:
        updated = await service.update_telegram(user.id, payload.telegram_enabled)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AuthUserOut.model_validate(updated)


@router.post("/auth/twitch/disconnect")
async def auth_disconnect(
    user: CurrentUserDep, service: AuthServiceDep
) -> dict:
    await service.disconnect(user.id)
    return {"disconnected": True}
