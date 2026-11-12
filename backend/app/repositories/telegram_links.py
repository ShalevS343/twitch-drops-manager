from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import TelegramLinkCode


class TelegramLinkRepository:
    """One-time Telegram link codes; only hashes are persisted."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, user_id: int, code_hash: str, expires_at: datetime
    ) -> TelegramLinkCode:
        row = TelegramLinkCode(
            user_id=user_id,
            code_hash=code_hash,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_hash(self, code_hash: str) -> TelegramLinkCode | None:
        result = await self.session.execute(
            select(TelegramLinkCode).where(
                TelegramLinkCode.code_hash == code_hash
            )
        )
        return result.scalar_one_or_none()

    async def mark_used(
        self, row: TelegramLinkCode, when: datetime | None = None
    ) -> TelegramLinkCode:
        row.used_at = when or datetime.now(timezone.utc)
        await self.session.flush()
        return row

    async def delete_for_user(self, user_id: int) -> None:
        await self.session.execute(
            delete(TelegramLinkCode).where(TelegramLinkCode.user_id == user_id)
        )
        await self.session.flush()

    async def delete_expired(self, when: datetime | None = None) -> None:
        await self.session.execute(
            delete(TelegramLinkCode).where(
                TelegramLinkCode.expires_at <= (when or datetime.now(timezone.utc))
            )
        )
        await self.session.flush()
