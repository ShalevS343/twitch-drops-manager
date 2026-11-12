from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_user, require_admin
from app.domain.models import User
from app.providers.telegram import TelegramProvider
from app.providers.twitch_user import TwitchUserProvider
from app.services.auth_service import AuthService
from app.services.factory import (
    build_progress_service,
    build_scan_service,
    get_telegram_provider,
    get_twitch_user_provider,
)
from app.services.progress_service import ProgressService
from app.services.scan_service import ScanService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_scan_service(session: SessionDep) -> ScanService:
    return build_scan_service(session)


async def get_progress_service(session: SessionDep) -> ProgressService:
    return build_progress_service(session)


ScanServiceDep = Annotated[ScanService, Depends(get_scan_service)]
ProgressServiceDep = Annotated[ProgressService, Depends(get_progress_service)]
TelegramDep = Annotated[TelegramProvider, Depends(get_telegram_provider)]
TwitchUserDep = Annotated[TwitchUserProvider, Depends(get_twitch_user_provider)]


async def get_auth_service(
    session: SessionDep, provider: TwitchUserDep
) -> AuthService:
    return AuthService(session, provider=provider)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user_dep(request: Request, session: SessionDep) -> User:
    return await get_current_user(request, session)


CurrentUserDep = Annotated[User, Depends(get_current_user_dep)]


async def get_admin_user_dep(user: CurrentUserDep) -> User:
    return require_admin(user)


AdminUserDep = Annotated[User, Depends(get_admin_user_dep)]
