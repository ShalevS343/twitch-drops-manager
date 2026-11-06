from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import DropProgress, ProgressSnapshot
from app.domain.parsing import campaign_gql_id_from_external_id, parse_iso_datetime
from app.domain.schemas import WatchQueueCampaignOut, WatchQueueItemOut
from app.repositories.progress import ProgressRepository
from app.repositories.streams import StreamRepository
from app.services.progress_metrics import (
    RATE_WINDOW,
    campaign_remaining_minutes,
    drop_metrics,
)


@dataclass(frozen=True)
class _CampaignSummary:
    campaign_id: str
    campaign_name: str
    ends_at: str | None
    remaining_minutes: int
    next_drop_name: str | None
    next_drop_remaining_minutes: int | None


@dataclass(frozen=True)
class FocusCandidate:
    stream: WatchQueueItemOut
    campaign: WatchQueueCampaignOut


def _build_campaign_summaries(
    rows: list[DropProgress],
    snapshots_by_drop: dict[str, list[ProgressSnapshot]],
    db_campaigns: dict[str, tuple[str, str | None]],
    now: datetime,
) -> dict[str, _CampaignSummary]:
    grouped: dict[str, list[DropProgress]] = {}
    for row in rows:
        if not row.campaign_gql_id:
            continue
        grouped.setdefault(row.campaign_gql_id, []).append(row)

    summaries: dict[str, _CampaignSummary] = {}
    for campaign_id, campaign_rows in grouped.items():
        metrics = {
            row.drop_id: drop_metrics(row, snapshots_by_drop.get(row.drop_id, []), now)
            for row in campaign_rows
        }
        remaining = campaign_remaining_minutes(
            (metrics[row.drop_id], row.is_claimed) for row in campaign_rows
        )

        unclaimed = [row for row in campaign_rows if not row.is_claimed]
        next_drop: DropProgress | None = None
        if unclaimed:
            positive = [
                row for row in unclaimed if metrics[row.drop_id].remaining_minutes > 0
            ]
            if positive:
                next_drop = min(
                    positive, key=lambda row: metrics[row.drop_id].remaining_minutes
                )
            else:
                next_drop = unclaimed[0]

        ends_at = next(
            (row.campaign_ends_at for row in campaign_rows if row.campaign_ends_at), None
        )
        db_name, db_ends_at = db_campaigns.get(campaign_id, ("", None))
        summaries[campaign_id] = _CampaignSummary(
            campaign_id=campaign_id,
            campaign_name=campaign_rows[0].campaign_name or db_name,
            ends_at=ends_at or db_ends_at,
            remaining_minutes=remaining,
            next_drop_name=next_drop.drop_name if next_drop is not None else None,
            next_drop_remaining_minutes=(
                metrics[next_drop.drop_id].remaining_minutes
                if next_drop is not None
                else None
            ),
        )

    return summaries


def _campaign_sort_key(summary: _CampaignSummary) -> tuple[int, float, str]:
    ends = parse_iso_datetime(summary.ends_at)
    if ends is None:
        return (1, 0.0, summary.campaign_name.lower())
    return (0, ends.timestamp(), summary.campaign_name.lower())


def _item_sort_key(
    item: WatchQueueItemOut, total_remaining: int
) -> tuple[int, float, int, int]:
    ends = [
        parsed
        for parsed in (parse_iso_datetime(campaign.ends_at) for campaign in item.campaigns)
        if parsed is not None
    ]
    if ends:
        ends_key: tuple[int, float] = (0, min(ends).timestamp())
    else:
        ends_key = (1, 0.0)

    return (ends_key[0], ends_key[1], -total_remaining, -item.viewers)


async def build_watch_queue(session: AsyncSession) -> list[WatchQueueItemOut]:
    """Build the urgency-sorted queue used by the API and the focus watcher."""
    progress_repo = ProgressRepository(session)
    progress_rows = await progress_repo.list()
    if not progress_rows:
        return []

    now = datetime.now(timezone.utc)
    snapshots = await progress_repo.snapshots_since(
        now - RATE_WINDOW, [row.drop_id for row in progress_rows]
    )
    snapshots_by_drop: dict[str, list[ProgressSnapshot]] = {}
    for snapshot in snapshots:
        snapshots_by_drop.setdefault(snapshot.drop_id, []).append(snapshot)

    rows = await StreamRepository(session).list_watch_queue_rows()

    db_campaigns: dict[str, tuple[str, str | None]] = {}
    for row in rows:
        gql_id = campaign_gql_id_from_external_id(row.external_id)
        if gql_id:
            db_campaigns.setdefault(gql_id, (row.campaign_name, row.ends_at))

    summaries = _build_campaign_summaries(
        progress_rows, snapshots_by_drop, db_campaigns, now
    )
    if not summaries:
        return []

    streams: dict[int, Any] = {}
    campaign_ids_by_stream: dict[int, list[str]] = {}
    seen_external_ids: dict[int, set[str]] = {}
    keyed_items: list[tuple[tuple[int, float, int, int], WatchQueueItemOut]] = []

    for row in rows:
        gql_id = campaign_gql_id_from_external_id(row.external_id)
        if gql_id not in summaries:
            continue

        if row.stream_id not in streams:
            streams[row.stream_id] = row
            campaign_ids_by_stream[row.stream_id] = []
            seen_external_ids[row.stream_id] = set()

        if row.external_id in seen_external_ids[row.stream_id]:
            continue
        seen_external_ids[row.stream_id].add(row.external_id)

        campaign_ids = campaign_ids_by_stream[row.stream_id]
        if gql_id not in campaign_ids:
            campaign_ids.append(gql_id)

    for stream_id, campaign_ids in campaign_ids_by_stream.items():
        stream = streams[stream_id]
        matched = [summaries[campaign_id] for campaign_id in campaign_ids]
        matched.sort(key=_campaign_sort_key)

        item = WatchQueueItemOut(
            stream_id=stream.stream_id,
            user_login=stream.user_login,
            user_name=stream.user_name,
            title=stream.title,
            viewers=stream.viewers,
            language=stream.language,
            url=stream.url,
            game_name=stream.game_name or "",
            game_box_art_url=stream.game_box_art_url or "",
            campaigns=[
                WatchQueueCampaignOut(
                    campaign_id=summary.campaign_id,
                    campaign_name=summary.campaign_name,
                    ends_at=summary.ends_at,
                    remaining_minutes=summary.remaining_minutes,
                    next_drop_name=summary.next_drop_name,
                    next_drop_remaining_minutes=summary.next_drop_remaining_minutes,
                )
                for summary in matched
            ],
        )
        total_remaining = max(
            (summary.remaining_minutes for summary in matched), default=0
        )
        keyed_items.append((_item_sort_key(item, total_remaining), item))

    keyed_items.sort(key=lambda pair: pair[0])
    return [item for _, item in keyed_items]


def find_candidate(
    items: list[WatchQueueItemOut],
    *,
    stream_id: int | None = None,
    campaign_id: str | None = None,
    exclude_stream_id: int | None = None,
) -> FocusCandidate | None:
    """Return the first dispatchable stream/campaign in queue order."""
    for item in items:
        if stream_id is not None and item.stream_id != stream_id:
            continue
        if exclude_stream_id is not None and item.stream_id == exclude_stream_id:
            continue

        for campaign in item.campaigns:
            if campaign_id is not None and campaign.campaign_id != campaign_id:
                continue
            if campaign.remaining_minutes <= 0:
                continue
            return FocusCandidate(stream=item, campaign=campaign)

    return None
