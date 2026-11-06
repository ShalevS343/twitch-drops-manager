"""Shared remaining-time and watch-rate calculations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

RATE_WINDOW = timedelta(hours=2)
MIN_RATE_SPAN_MINUTES = 5.0
MIN_RATE_MINUTES_PER_HOUR = 0.5


@dataclass(frozen=True)
class DropMetrics:
    remaining_minutes: int
    rate_minutes_per_hour: float | None


def to_utc(value: datetime) -> datetime:
    """Treat naive datetimes (as returned by SQLite) as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def drop_remaining_minutes(drop: Any) -> int:
    if bool(getattr(drop, "is_claimed", False)):
        return 0

    required = int(getattr(drop, "required_minutes", 0) or 0)
    current = int(getattr(drop, "current_minutes", 0) or 0)
    return max(0, required - current)


def watch_rate(snapshots: Iterable[Any], now: datetime) -> float | None:
    """Minutes watched per hour, based on the last two hours of snapshots."""
    now = to_utc(now)
    cutoff = now - RATE_WINDOW

    points = sorted(
        (to_utc(snapshot.recorded_at), int(snapshot.current_minutes or 0))
        for snapshot in snapshots
        if to_utc(snapshot.recorded_at) >= cutoff
    )
    if len(points) < 2:
        return None

    oldest_at, oldest_minutes = points[0]
    newest_at, newest_minutes = points[-1]
    span_minutes = (newest_at - oldest_at).total_seconds() / 60
    if span_minutes < MIN_RATE_SPAN_MINUTES:
        return None

    rate = (newest_minutes - oldest_minutes) * 60 / span_minutes
    if rate < MIN_RATE_MINUTES_PER_HOUR:
        return None
    return rate


def drop_metrics(drop: Any, snapshots: Iterable[Any], now: datetime) -> DropMetrics:
    remaining = drop_remaining_minutes(drop)
    rate = watch_rate(snapshots, now)
    return DropMetrics(
        remaining_minutes=remaining,
        rate_minutes_per_hour=rate,
    )


def campaign_remaining_minutes(items: Iterable[tuple[DropMetrics, bool]]) -> int:
    """Remaining watch time for one campaign.

    Drop requirements are not additive: watch time counts toward every open drop
    in the campaign, so finishing a 1h drop and a 2h drop takes 2h, not 3h. The
    campaign therefore needs the **largest** remaining drop requirement.
    """
    return max(
        (metrics.remaining_minutes for metrics, claimed in items if not claimed),
        default=0,
    )
