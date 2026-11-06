from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.domain.models import Campaign, Game, Stream
from app.domain.schemas import ScanRunOut, StatusOut
from app.repositories.games import GameRepository
from app.repositories.scans import ScanRunRepository
from app.services.factory import get_telegram_provider, get_twitch_provider

router = APIRouter()


@router.get("/status", response_model=StatusOut)
async def status(session: SessionDep) -> StatusOut:
    selected = await GameRepository(session).list_selected()

    campaign_count = await session.scalar(
        select(func.count())
        .select_from(Campaign)
        .join(Game)
        .where(Game.selected.is_(True))
    )
    stream_count = await session.scalar(
        select(func.count())
        .select_from(Stream)
        .join(Game)
        .where(Game.selected.is_(True), Stream.live.is_(True))
    )
    latest = await ScanRunRepository(session).latest()

    return StatusOut(
        app=get_settings().app_name,
        twitch_configured=get_twitch_provider().ready,
        telegram_configured=get_telegram_provider().configured,
        games_selected=[game.name for game in selected],
        campaign_count=int(campaign_count or 0),
        stream_count=int(stream_count or 0),
        last_scan=ScanRunOut.model_validate(latest) if latest else None,
        last_error=latest.error if latest and not latest.ok else None,
    )
