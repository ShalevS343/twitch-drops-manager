from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import UserSession


class UserSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> UserSession:
        timestamp = now or datetime.now(timezone.utc)
        row = UserSession(
            user_id=user_id,
            token_hash=token_hash,
            csrf_token_hash=csrf_token_hash,
            created_at=timestamp,
            last_used_at=timestamp,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        result = await self.session.execute(
            select(UserSession).where(UserSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def touch(self, row: UserSession, when: datetime | None = None) -> None:
        row.last_used_at = when or datetime.now(timezone.utc)
        await self.session.flush()

    async def delete_by_token_hash(self, token_hash: str) -> None:
        await self.session.execute(
            delete(UserSession).where(UserSession.token_hash == token_hash)
        )
        await self.session.flush()

    async def delete_for_user(self, user_id: int) -> None:
        await self.session.execute(
            delete(UserSession).where(UserSession.user_id == user_id)
        )
        await self.session.flush()

    async def delete_expired(self, now: datetime | None = None) -> None:
        cutoff = now or datetime.now(timezone.utc)
        await self.session.execute(
            delete(UserSession).where(UserSession.expires_at <= cutoff)
        )
        await self.session.flush()
