from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUserDep, SessionDep
from app.core.config import get_settings
from app.domain.models import Campaign, Game, Stream
from app.domain.schemas import AuthUserOut, ScanRunOut, StatusOut
from app.repositories.scans import ScanRunRepository
from app.repositories.twitch_accounts import TwitchAccountRepository
from app.repositories.user_games import UserGameRepository
from app.services.factory import get_telegram_provider, get_twitch_provider

router = APIRouter()


@router.get("/status", response_model=StatusOut)
async def status(session: SessionDep, user: CurrentUserDep) -> StatusOut:
    games = await UserGameRepository(session).list_games(user.id)
    selected_ids = {game.id for game in games}

    campaign_count = 0
    stream_count = 0
    if selected_ids:
        campaign_count = await session.scalar(
            select(func.count())
            .select_from(Campaign)
            .join(Game)
            .where(Game.id.in_(selected_ids))
        ) or 0
        stream_count = await session.scalar(
            select(func.count())
            .select_from(Stream)
            .join(Game)
            .where(Game.id.in_(selected_ids), Stream.live.is_(True))
        ) or 0

    latest = await ScanRunRepository(session).latest()
    account = await TwitchAccountRepository(session).get_for_user(user.id)
    settings = get_settings()
    telegram = get_telegram_provider()

    return StatusOut(
        app=settings.app_name,
        user=AuthUserOut.model_validate(user),
        twitch_configured=get_twitch_provider().ready,
        telegram_configured=telegram.configured,
        telegram_ready=bool(
            telegram.configured
            and user.telegram_enabled
            and user.telegram_chat_id.strip()
        ),
        games_selected=[game.name for game in games],
        campaign_count=int(campaign_count),
        stream_count=int(stream_count),
        last_scan=ScanRunOut.model_validate(latest) if latest else None,
        last_error=latest.error if latest and not latest.ok else None,
        twitch_user_connected=account is not None,
        twitch_login=(user.login or None) if account is not None else None,
        poll_seconds=settings.poll_seconds,
        min_poll_seconds=settings.min_poll_seconds,
        progress_poll_seconds=settings.progress_poll_seconds,
        min_progress_poll_seconds=settings.min_progress_poll_seconds,
        watcher_poll_seconds=settings.watcher_poll_seconds,
        min_watcher_poll_seconds=settings.min_watcher_poll_seconds,
        drops_api_keyed=bool(settings.drops_api_key),
    )
