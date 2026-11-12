from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import UserWatchFocus


class WatchFocusRepository:
    """One focus pointer per user."""

    def __init__(self, session: AsyncSession, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    async def get(self) -> UserWatchFocus | None:
        result = await self.session.execute(
            select(UserWatchFocus).where(UserWatchFocus.user_id == self.user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self) -> UserWatchFocus:
        row = await self.get()
        if row is not None:
            return row

        row = UserWatchFocus(user_id=self.user_id)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            # The API and worker are separate processes; another writer may
            # have created this user's row first. Reload it instead of failing.
            row = await self.get()
            if row is None:
                raise
        return row
