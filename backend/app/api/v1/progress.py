from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CurrentUserDep,
    ProgressServiceDep,
    SessionDep,
    TwitchUserDep,
)
from app.core.exceptions import (
    NotConfiguredError,
    ProviderError,
    ReconnectRequiredError,
)
from app.core.rate_limit import enforce_user_action_limit
from app.domain.models import Campaign, UserDropProgress, UserProgressSnapshot
from app.domain.parsing import campaign_gql_id_from_external_id
from app.domain.schemas import (
    ProgressCampaignOut,
    ProgressDropOut,
    ProgressRefreshOut,
    TwitchUserStatusOut,
)
from app.repositories.campaign_completions import CampaignCompletionRepository
from app.repositories.campaigns import CampaignRepository
from app.repositories.progress import ProgressRepository
from app.repositories.twitch_accounts import TwitchAccountRepository
from app.services.profile_service import get_profile_service
from app.services.progress_metrics import RATE_WINDOW, drop_metrics

router = APIRouter()


def _percent(drop: UserDropProgress) -> int:
    if drop.required_minutes <= 0:
        return 100 if drop.is_claimed else 0
    if drop.is_claimed:
        return 100
    return max(0, min(100, round(drop.current_minutes * 100 / drop.required_minutes)))


def _group_progress(
    rows: list[UserDropProgress],
    snapshots_by_drop: dict[str, list[UserProgressSnapshot]] | None = None,
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
        grouped.values(),
        key=lambda item: (
            item.game_name.lower(),
            item.campaign_name.lower(),
        ),
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
async def list_progress(
    session: SessionDep, user: CurrentUserDep
) -> list[ProgressCampaignOut]:
    repo = ProgressRepository(session, user.id)
    rows = await repo.list()
    now = datetime.now(timezone.utc)
    snapshots = await repo.snapshots_since(
        now - RATE_WINDOW, [row.drop_id for row in rows]
    )

    snapshots_by_drop: dict[str, list[UserProgressSnapshot]] = {}
    for snapshot in snapshots:
        snapshots_by_drop.setdefault(snapshot.drop_id, []).append(snapshot)

    campaigns = _group_progress(rows, snapshots_by_drop, now)
    completed = await CampaignCompletionRepository(session, user.id).list()
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


@router.post("/progress/refresh", response_model=ProgressRefreshOut)
async def refresh_progress(
    user: CurrentUserDep, service: ProgressServiceDep
) -> ProgressRefreshOut:
    enforce_user_action_limit("progress.refresh", user.id)
    try:
        result = await service.run()
    except ReconnectRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
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
async def twitch_status(
    session: SessionDep, user: CurrentUserDep, provider: TwitchUserDep
) -> TwitchUserStatusOut:
    account = await TwitchAccountRepository(session).get_for_user(user.id)
    if account is None:
        return TwitchUserStatusOut(connected=False)

    if not user.display_name:
        # Never block this request on Twitch GQL. The next poll (or the startup
        # warm-up) stores the profile in the background and returns it then.
        get_profile_service().schedule(user.id, provider)

    return TwitchUserStatusOut(
        connected=True,
        login=user.login or None,
        user_id=user.twitch_user_id or None,
        expires_at=account.expires_at,
        display_name=user.display_name or user.login or None,
        profile_image_url=user.profile_image_url or None,
        connected_at=account.connected_at,
        reconnect_required=account.reconnect_required,
        last_error=account.last_error or None,
        last_synced_at=account.last_synced_at,
    )
