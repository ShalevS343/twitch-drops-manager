import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ProgressServiceDep, SessionDep, TwitchUserDep
from app.core.db import SessionLocal
from app.core.exceptions import NotConfiguredError, ProviderError
from app.core.security import require_api_token
from app.domain.models import Campaign, DropProgress, ProgressSnapshot
from app.domain.parsing import campaign_gql_id_from_external_id
from app.domain.schemas import (
    ProgressCampaignOut,
    ProgressDropOut,
    ProgressRefreshOut,
    TwitchConnectIn,
    TwitchConnectOut,
    TwitchConnectResult,
    TwitchUserStatusOut,
)
from app.repositories.campaign_completions import CampaignCompletionRepository
from app.repositories.campaigns import CampaignRepository
from app.repositories.progress import ProgressRepository
from app.repositories.twitch_auth import TwitchAuthRepository
from app.repositories.twitch_profile import TwitchProfileRepository
from app.services.factory import build_progress_service, get_twitch_user_provider
from app.services.progress_metrics import RATE_WINDOW, drop_metrics

router = APIRouter()

# Background profile fetches are tracked so shutdown can cancel them, and each
# user gets at most one in-flight fetch at a time.
_profile_refresh_tasks: set[asyncio.Task[None]] = set()
_profile_refresh_inflight: set[str] = set()


async def _fetch_and_save_profile(
    session,
    provider,
    *,
    user_id: str,
    access_token: str,
    connected_at: datetime,
):
    """Fetch the Twitch profile and persist it, even when the fetch fails.

    A failed fetch stores an empty profile row. That keeps ``/twitch/status``
    DB-only afterwards (we deliberately do not retry GQL on every request);
    the profile is refreshed on the next connect.
    """
    display_name = ""
    profile_image_url = ""
    try:
        profile = await provider.fetch_profile(access_token, user_id)
        display_name = str(profile.get("displayName") or "")
        profile_image_url = str(profile.get("profileImageURL") or "")
    except (NotConfiguredError, ProviderError):
        pass

    return await TwitchProfileRepository(session).save(
        user_id=user_id,
        display_name=display_name,
        profile_image_url=profile_image_url,
        connected_at=connected_at,
    )


async def refresh_twitch_profile(
    user_id: str,
    provider=None,
    session_factory=None,
) -> None:
    """Fetch and store the Twitch profile in its own session.

    Used by the non-blocking cold path: ``/twitch/status`` never waits for
    Twitch GQL, and the next poll returns the stored profile.
    """
    factory = session_factory or SessionLocal

    async with factory() as session:
        auth = await TwitchAuthRepository(session).get()
        if auth is None:
            return
        if user_id and (auth.user_id or "") != user_id:
            return
        if await TwitchProfileRepository(session).get() is not None:
            return

        await _fetch_and_save_profile(
            session,
            provider or get_twitch_user_provider(),
            user_id=auth.user_id or "",
            access_token=auth.access_token,
            connected_at=auth.updated_at,
        )
        await session.commit()


async def _run_profile_refresh(user_id: str, provider=None) -> None:
    try:
        await refresh_twitch_profile(user_id, provider)
    finally:
        _profile_refresh_inflight.discard(user_id)


def _track_task(coro) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)
    _profile_refresh_tasks.add(task)
    task.add_done_callback(_profile_refresh_tasks.discard)
    return task


def schedule_profile_refresh(user_id: str, provider=None) -> asyncio.Task[None] | None:
    """Schedule one background refresh per user, or return None if already busy."""
    if user_id in _profile_refresh_inflight:
        return None

    _profile_refresh_inflight.add(user_id)
    try:
        return _track_task(_run_profile_refresh(user_id, provider))
    except RuntimeError:
        _profile_refresh_inflight.discard(user_id)
        return None


async def _warm_up_profile_on_startup(session_factory=None) -> None:
    factory = session_factory or SessionLocal

    async with factory() as session:
        auth = await TwitchAuthRepository(session).get()
        if auth is None:
            return
        if await TwitchProfileRepository(session).get() is not None:
            return
        user_id = auth.user_id or ""

    schedule_profile_refresh(user_id)


def start_profile_refresh_warmup() -> None:
    """Start the startup profile check without blocking the lifespan."""
    _track_task(_warm_up_profile_on_startup())


async def shutdown_profile_refresh() -> None:
    """Cancel in-flight background profile fetches during shutdown."""
    while _profile_refresh_tasks:
        tasks = list(_profile_refresh_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    _profile_refresh_tasks.clear()
    _profile_refresh_inflight.clear()


def _percent(drop: DropProgress) -> int:
    if drop.required_minutes <= 0:
        return 100 if drop.is_claimed else 0
    if drop.is_claimed:
        return 100
    return max(0, min(100, round(drop.current_minutes * 100 / drop.required_minutes)))


def _group_progress(
    rows: list[DropProgress],
    snapshots_by_drop: dict[str, list[ProgressSnapshot]] | None = None,
    now: datetime | None = None,
) -> list[ProgressCampaignOut]:
    snapshots_by_drop = snapshots_by_drop or {}
    now = now or datetime.now(timezone.utc)
    grouped: dict[str, ProgressCampaignOut] = {}

    for row in rows:
        key = row.campaign_gql_id or row.campaign_name
        campaign = grouped.get(key)
        if campaign is None:
            campaign = ProgressCampaignOut(
                campaign_id=row.campaign_gql_id,
                campaign_name=row.campaign_name,
                game_name=row.game_name,
                game_box_art_url=row.game_box_art_url,
                campaign_ends_at=row.campaign_ends_at,
            )
            grouped[key] = campaign

        metrics = drop_metrics(row, snapshots_by_drop.get(row.drop_id, []), now)
        campaign.drops.append(
            ProgressDropOut(
                drop_id=row.drop_id,
                drop_name=row.drop_name,
                required_minutes=row.required_minutes,
                current_minutes=row.current_minutes,
                percent=_percent(row),
                is_claimed=row.is_claimed,
                is_ready=row.is_ready,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                benefits=row.benefits or [],
                remaining_minutes=metrics.remaining_minutes,
                rate_minutes_per_hour=metrics.rate_minutes_per_hour,
            )
        )

    for campaign in grouped.values():
        campaign.total_count = len(campaign.drops)
        campaign.claimed_count = sum(1 for drop in campaign.drops if drop.is_claimed)

        unclaimed = [drop for drop in campaign.drops if not drop.is_claimed]
        # Drops share the same watch time, so the campaign finishes when its
        # largest remaining drop does — do not add the drop requirements.
        campaign.remaining_minutes = max(
            (drop.remaining_minutes for drop in unclaimed), default=0
        )

    return sorted(
        grouped.values(), key=lambda item: (item.game_name.lower(), item.campaign_name.lower())
    )


def _completed_campaign_out(campaign: Campaign) -> ProgressCampaignOut:
    drops = [
        ProgressDropOut(
            drop_id=f"completed:{campaign.external_id}:{reward.id}",
            drop_name=reward.name,
            required_minutes=reward.required_minutes,
            current_minutes=reward.required_minutes,
            percent=100,
            is_claimed=True,
            is_ready=False,
            starts_at=campaign.starts_at,
            ends_at=campaign.ends_at,
            benefits=[reward.benefit_name] if reward.benefit_name else [],
            remaining_minutes=0,
            rate_minutes_per_hour=None,
        )
        for reward in campaign.rewards
    ]
    return ProgressCampaignOut(
        campaign_id=campaign_gql_id_from_external_id(campaign.external_id),
        campaign_name=campaign.name,
        game_name=campaign.game.name if campaign.game else "",
        game_box_art_url=campaign.game.box_art_url if campaign.game else "",
        campaign_ends_at=campaign.ends_at,
        claimed_count=len(drops),
        total_count=len(drops),
        drops=drops,
        remaining_minutes=0,
    )


@router.get("/progress", response_model=list[ProgressCampaignOut])
async def list_progress(session: SessionDep) -> list[ProgressCampaignOut]:
    repo = ProgressRepository(session)
    rows = await repo.list()
    now = datetime.now(timezone.utc)
    snapshots = await repo.snapshots_since(
        now - RATE_WINDOW, [row.drop_id for row in rows]
    )

    snapshots_by_drop: dict[str, list[ProgressSnapshot]] = {}
    for snapshot in snapshots:
        snapshots_by_drop.setdefault(snapshot.drop_id, []).append(snapshot)

    campaigns = _group_progress(rows, snapshots_by_drop, now)
    completed = await CampaignCompletionRepository(session).list()
    completed_ids = {row.campaign_gql_id for row in completed}
    existing = {campaign.campaign_id for campaign in campaigns}

    missing = completed_ids - existing
    if missing:
        catalog = await CampaignRepository(session).list()
        by_gql_id = {
            campaign_gql_id_from_external_id(campaign.external_id): campaign
            for campaign in catalog
        }
        for campaign_id in sorted(missing):
            campaign = by_gql_id.get(campaign_id)
            if campaign is not None and campaign.rewards:
                campaigns.append(_completed_campaign_out(campaign))

    return sorted(
        campaigns,
        key=lambda item: (
            item.campaign_id in completed_ids,
            item.game_name.lower(),
            item.campaign_name.lower(),
        ),
    )


@router.post(
    "/progress/refresh",
    response_model=ProgressRefreshOut,
    dependencies=[Depends(require_api_token)],
)
async def refresh_progress(service: ProgressServiceDep) -> ProgressRefreshOut:
    try:
        result = await service.run()
    except NotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return ProgressRefreshOut(
        connected=result.connected,
        campaign_count=result.campaign_count,
        drop_count=result.drop_count,
        notified_count=result.notified_count,
    )


@router.get("/twitch/status", response_model=TwitchUserStatusOut)
async def twitch_status(session: SessionDep, provider: TwitchUserDep) -> TwitchUserStatusOut:
    auth = await TwitchAuthRepository(session).get()
    if auth is None:
        return TwitchUserStatusOut(connected=False)

    profile = await TwitchProfileRepository(session).get()
    if profile is None:
        # Never block this request on Twitch GQL. The next poll (or the startup
        # warm-up) stores the profile in the background and returns it then.
        schedule_profile_refresh(auth.user_id or "", provider)
        return TwitchUserStatusOut(
            connected=True,
            login=auth.login or None,
            user_id=auth.user_id or None,
            expires_at=auth.expires_at,
            display_name=auth.login or None,
            profile_image_url=None,
            connected_at=auth.updated_at,
        )

    return TwitchUserStatusOut(
        connected=True,
        login=auth.login or None,
        user_id=auth.user_id or None,
        expires_at=auth.expires_at,
        display_name=profile.display_name or auth.login or None,
        profile_image_url=profile.profile_image_url or None,
        connected_at=profile.connected_at or auth.updated_at,
    )


@router.get("/twitch/connect", response_model=TwitchConnectOut)
async def twitch_connect_url(provider: TwitchUserDep) -> TwitchConnectOut:
    return TwitchConnectOut(
        authorize_url=provider.authorize_url,
        redirect_uri=provider.settings.twitch_oauth_redirect_uri,
    )


@router.post(
    "/twitch/connect",
    response_model=TwitchConnectResult,
    dependencies=[Depends(require_api_token)],
)
async def twitch_connect(
    payload: TwitchConnectIn, session: SessionDep, provider: TwitchUserDep
) -> TwitchConnectResult:
    token = provider.parse_oauth_token(payload.redirect_url)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not find an access token in the pasted URL",
        )

    try:
        info = await provider.validate(token)
    except NotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    expected_client = provider.settings.gql_client_id
    if str(info.get("client_id") or "") != expected_client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That token was issued for a different Twitch client. "
                "Use the Connect Twitch link on this page and paste the URL "
                "Twitch redirects you to."
            ),
        )

    expires_in = int(info.get("expires_in") or 0)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if expires_in > 0
        else None
    )
    user_id = str(info.get("user_id") or "")
    await TwitchAuthRepository(session).save(
        user_id=user_id,
        login=str(info.get("login") or ""),
        access_token=token,
        refresh_token="",
        expires_at=expires_at,
    )
    await session.commit()

    await _fetch_and_save_profile(
        session,
        provider,
        user_id=user_id,
        access_token=token,
        connected_at=datetime.now(timezone.utc),
    )
    await session.commit()

    message = None
    try:
        result = await build_progress_service(session).run()
        if not result.drop_count:
            message = "Connected, but no in-progress drops were found yet."
    except (NotConfiguredError, ProviderError) as exc:
        message = f"Connected, but the first sync failed: {exc}"

    return TwitchConnectResult(
        connected=True,
        login=str(info.get("login") or "") or None,
        message=message,
    )


@router.post(
    "/twitch/logout",
    dependencies=[Depends(require_api_token)],
)
async def twitch_logout(session: SessionDep) -> dict:
    await TwitchAuthRepository(session).clear()
    await TwitchProfileRepository(session).clear()
    await ProgressRepository(session).replace([])
    await session.commit()
    return {"disconnected": True}
