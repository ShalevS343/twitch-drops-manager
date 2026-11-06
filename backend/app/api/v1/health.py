from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.services.factory import get_telegram_provider, get_twitch_provider

router = APIRouter()


@router.get("/health")
async def health(session: SessionDep) -> dict:
    settings = get_settings()
    try:
        await session.execute(text("SELECT 1"))
        database_ok = True
    except SQLAlchemyError:
        database_ok = False

    return {
        "ok": database_ok,
        "database": database_ok,
        "twitch_api_configured": get_twitch_provider().ready,
        "telegram_configured": get_telegram_provider().configured,
        "drops_api_configured": True,
        "drops_api_keyed": bool(settings.drops_api_key),
    }
