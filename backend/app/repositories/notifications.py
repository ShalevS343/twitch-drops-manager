from sqlalchemy import select
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
