from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import DropProgress, ProgressSnapshot


class ProgressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[DropProgress]:
        result = await self.session.execute(
            select(DropProgress).order_by(
                DropProgress.game_name,
                DropProgress.campaign_name,
                DropProgress.required_minutes,
                DropProgress.drop_name,
            )
        )
        return list(result.scalars().all())

    async def replace(self, rows: list[dict[str, Any]]) -> None:
        # The inventory response is the full current state, so replacing is
        # simpler (and avoids stale rows) than trying to diff each drop.
        await self.session.execute(delete(DropProgress))
        for row in rows:
            self.session.add(DropProgress(**row))
        await self.session.flush()

    async def add_snapshots(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self.session.add(
                ProgressSnapshot(
                    drop_id=row["drop_id"],
                    current_minutes=int(row.get("current_minutes") or 0),
                )
            )
        await self.session.flush()

    async def prune_snapshots(self, before: datetime) -> None:
        await self.session.execute(
            delete(ProgressSnapshot).where(ProgressSnapshot.recorded_at < before)
        )

    async def snapshots_since(
        self, since: datetime, drop_ids: list[str] | None = None
    ) -> list[ProgressSnapshot]:
        if drop_ids is not None and not drop_ids:
            return []

        stmt = (
            select(ProgressSnapshot)
            .where(ProgressSnapshot.recorded_at >= since)
            .order_by(ProgressSnapshot.drop_id, ProgressSnapshot.recorded_at)
        )
        if drop_ids is not None:
            stmt = stmt.where(ProgressSnapshot.drop_id.in_(drop_ids))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
