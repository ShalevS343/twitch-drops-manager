from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.providers.telegram import TelegramProvider
from app.providers.twitch_user import TwitchUserProvider
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
