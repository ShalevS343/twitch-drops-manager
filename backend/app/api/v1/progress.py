from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ProgressServiceDep, SessionDep, TwitchUserDep
from app.core.exceptions import NotConfiguredError, ProviderError
from app.core.security import require_api_token
from app.domain.models import DropProgress, ProgressSnapshot
from app.domain.schemas import (
    ProgressCampaignOut,
    ProgressDropOut,
    ProgressRefreshOut,
    TwitchConnectIn,
    TwitchConnectOut,
    TwitchConnectResult,
    TwitchUserStatusOut,
)
from app.repositories.progress import ProgressRepository
from app.repositories.twitch_auth import TwitchAuthRepository
from app.services.factory import build_progress_service
from app.services.progress_metrics import RATE_WINDOW, drop_metrics

router = APIRouter()


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
                eta_minutes=metrics.eta_minutes,
            )
        )

    for campaign in grouped.values():
        campaign.total_count = len(campaign.drops)
        campaign.claimed_count = sum(1 for drop in campaign.drops if drop.is_claimed)

        unclaimed = [drop for drop in campaign.drops if not drop.is_claimed]
        campaign.remaining_minutes = sum(drop.remaining_minutes for drop in unclaimed)
        etas = [drop.eta_minutes for drop in unclaimed]
        campaign.eta_minutes = (
            sum(eta for eta in etas if eta is not None)
            if all(eta is not None for eta in etas)
            else None
        )

    return sorted(
        grouped.values(), key=lambda item: (item.game_name.lower(), item.campaign_name.lower())
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

    return _group_progress(rows, snapshots_by_drop, now)


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

    display_name = auth.login or None
    profile_image_url = None
    try:
        profile = await provider.fetch_profile(auth.access_token, auth.user_id or "")
        display_name = str(profile.get("displayName") or "") or display_name
        profile_image_url = str(profile.get("profileImageURL") or "") or None
    except (NotConfiguredError, ProviderError):
        display_name = auth.login or None
        profile_image_url = None

    return TwitchUserStatusOut(
        connected=True,
        login=auth.login or None,
        user_id=auth.user_id or None,
        expires_at=auth.expires_at,
        display_name=display_name,
        profile_image_url=profile_image_url,
        connected_at=auth.updated_at,
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
    await TwitchAuthRepository(session).save(
        user_id=str(info.get("user_id") or ""),
        login=str(info.get("login") or ""),
        access_token=token,
        refresh_token="",
        expires_at=expires_at,
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
    await ProgressRepository(session).replace([])
    await session.commit()
    return {"disconnected": True}
