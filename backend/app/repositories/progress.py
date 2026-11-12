from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import UserDropProgress, UserProgressSnapshot


class ProgressRepository:
    """Per-user drop progress and watch-rate snapshots."""

    def __init__(self, session: AsyncSession, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    async def list(self) -> list[UserDropProgress]:
        result = await self.session.execute(
            select(UserDropProgress)
            .where(UserDropProgress.user_id == self.user_id)
            .order_by(
                UserDropProgress.game_name,
                UserDropProgress.campaign_name,
                UserDropProgress.required_minutes,
                UserDropProgress.drop_name,
            )
        )
        return list(result.scalars().all())

    async def replace(self, rows: list[dict[str, Any]]) -> None:
        # The inventory response is the full current state, so replacing is
        # simpler (and avoids stale rows) than trying to diff each drop.
        await self.session.execute(
            delete(UserDropProgress).where(
                UserDropProgress.user_id == self.user_id
            )
        )
        for row in rows:
            self.session.add(UserDropProgress(user_id=self.user_id, **row))
        await self.session.flush()

    async def add_snapshots(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self.session.add(
                UserProgressSnapshot(
                    user_id=self.user_id,
                    drop_id=row["drop_id"],
                    current_minutes=int(row.get("current_minutes") or 0),
                )
            )
        await self.session.flush()

    async def prune_snapshots(self, before: datetime) -> None:
        await self.session.execute(
            delete(UserProgressSnapshot).where(
                UserProgressSnapshot.user_id == self.user_id,
                UserProgressSnapshot.recorded_at < before,
            )
        )

    async def snapshots_since(
        self, since: datetime, drop_ids: list[str] | None = None
    ) -> list[UserProgressSnapshot]:
        if drop_ids is not None and not drop_ids:
            return []

        stmt = (
            select(UserProgressSnapshot)
            .where(
                UserProgressSnapshot.user_id == self.user_id,
                UserProgressSnapshot.recorded_at >= since,
            )
            .order_by(
                UserProgressSnapshot.drop_id,
                UserProgressSnapshot.recorded_at,
            )
        )
        if drop_ids is not None:
            stmt = stmt.where(UserProgressSnapshot.drop_id.in_(drop_ids))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
