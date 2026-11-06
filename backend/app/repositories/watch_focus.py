from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import WatchFocus

SINGLETON_ID = 1


class WatchFocusRepository:
    """Query the single watcher row.

    Focused mode is intentionally limited to one watcher, so the table is a
    singleton keyed by ``id=1``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> WatchFocus | None:
        result = await self.session.execute(
            select(WatchFocus).where(WatchFocus.id == SINGLETON_ID)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self) -> WatchFocus:
        row = await self.get()
        if row is not None:
            return row

        row = WatchFocus(id=SINGLETON_ID)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            # The API and worker are separate processes; another writer may
            # have created the singleton first. Reload it instead of failing.
            row = await self.get()
            if row is None:
                raise
        return row
