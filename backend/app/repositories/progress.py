from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import DropProgress


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
