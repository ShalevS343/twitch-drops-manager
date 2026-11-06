from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, dedupe_key: str) -> bool:
        result = await self.session.execute(
            select(Notification.id).where(Notification.dedupe_key == dedupe_key)
        )
        return result.first() is not None

    async def mark_sent(self, dedupe_key: str) -> None:
        self.session.add(Notification(dedupe_key=dedupe_key))
        await self.session.flush()

    async def claim(self, dedupe_key: str) -> bool:
        """Atomically reserve a dedupe key, returning False if already claimed."""
        try:
            async with self.session.begin_nested():
                self.session.add(Notification(dedupe_key=dedupe_key))
                await self.session.flush()
        except IntegrityError:
            return False
        return True

    async def release(self, dedupe_key: str) -> None:
        await self.session.execute(
            delete(Notification).where(Notification.dedupe_key == dedupe_key)
        )
        await self.session.flush()
