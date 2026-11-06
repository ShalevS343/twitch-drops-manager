"""Shared remaining-time, watch-rate and ETA calculations."""

from __future__ import annotations

import math
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
    eta_minutes: int | None


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


def eta_minutes(remaining_minutes: int, rate: float | None) -> int | None:
    if not rate or remaining_minutes <= 0:
        return None
    return math.ceil(remaining_minutes / rate * 60)


def drop_metrics(drop: Any, snapshots: Iterable[Any], now: datetime) -> DropMetrics:
    remaining = drop_remaining_minutes(drop)
    rate = watch_rate(snapshots, now)
    return DropMetrics(
        remaining_minutes=remaining,
        rate_minutes_per_hour=rate,
        eta_minutes=eta_minutes(remaining, rate),
    )


def campaign_totals(
    items: Iterable[tuple[DropMetrics, bool]],
) -> tuple[int, int | None]:
    """Aggregate drop metrics for one campaign.

    ``items`` contains ``(metrics, is_claimed)`` pairs. The campaign ETA is
    only meaningful when every unclaimed drop has an ETA of its own.
    """
    remaining = 0
    etas: list[int | None] = []

    for metrics, claimed in items:
        if claimed:
            continue
        remaining += metrics.remaining_minutes
        etas.append(metrics.eta_minutes)

    if all(eta is not None for eta in etas):
        return remaining, sum(eta for eta in etas if eta is not None)
    return remaining, None
