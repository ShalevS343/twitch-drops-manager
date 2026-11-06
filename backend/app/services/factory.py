from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.sunkwi import SunkwiProvider
from app.providers.telegram import TelegramProvider
from app.providers.twitch import TwitchProvider
from app.services.scan_service import ScanService


@lru_cache
def get_sunkwi_provider() -> SunkwiProvider:
    return SunkwiProvider(get_settings())


@lru_cache
def get_twitch_provider() -> TwitchProvider:
    return TwitchProvider(get_settings())


@lru_cache
def get_telegram_provider() -> TelegramProvider:
    return TelegramProvider(get_settings())


def build_scan_service(session: AsyncSession) -> ScanService:
    return ScanService(
        session=session,
        settings=get_settings(),
        sunkwi=get_sunkwi_provider(),
        twitch=get_twitch_provider(),
        telegram=get_telegram_provider(),
    )
