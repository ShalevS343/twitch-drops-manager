from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.providers.telegram import TelegramProvider
from app.services.factory import build_scan_service, get_telegram_provider
from app.services.scan_service import ScanService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_scan_service(session: SessionDep) -> ScanService:
    return build_scan_service(session)


ScanServiceDep = Annotated[ScanService, Depends(get_scan_service)]
TelegramDep = Annotated[TelegramProvider, Depends(get_telegram_provider)]
