from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import UserNotification


class NotificationRepository:
    """Per-user notification dedupe ledger."""

    def __init__(self, session: AsyncSession, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    async def exists(self, dedupe_key: str) -> bool:
        result = await self.session.execute(
            select(UserNotification.id).where(
                UserNotification.user_id == self.user_id,
                UserNotification.dedupe_key == dedupe_key,
            )
        )
        return result.first() is not None

    async def mark_sent(self, dedupe_key: str) -> None:
        self.session.add(
            UserNotification(user_id=self.user_id, dedupe_key=dedupe_key)
        )
        await self.session.flush()

    async def claim(self, dedupe_key: str) -> bool:
        """Atomically reserve a dedupe key for this user."""
        try:
            async with self.session.begin_nested():
                self.session.add(
                    UserNotification(
                        user_id=self.user_id, dedupe_key=dedupe_key
                    )
                )
                await self.session.flush()
        except IntegrityError:
            return False
        return True

    async def release(self, dedupe_key: str) -> None:
        await self.session.execute(
            delete(UserNotification).where(
                UserNotification.user_id == self.user_id,
                UserNotification.dedupe_key == dedupe_key,
            )
        )
        await self.session.flush()
