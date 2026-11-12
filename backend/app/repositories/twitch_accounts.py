from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import TwitchAccount


class TwitchAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(self, user_id: int) -> TwitchAccount | None:
        result = await self.session.execute(
            select(TwitchAccount).where(TwitchAccount.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[TwitchAccount]:
        result = await self.session.execute(
            select(TwitchAccount).order_by(TwitchAccount.user_id)
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        user_id: int,
        access_token: str,
        expires_at: datetime | None,
        connected_at: datetime | None = None,
        reconnect_required: bool = False,
        last_error: str = "",
    ) -> TwitchAccount:
        account = await self.get_for_user(user_id)
        if account is None:
            account = TwitchAccount(user_id=user_id)
            self.session.add(account)

        account.access_token = access_token
        account.expires_at = expires_at
        account.connected_at = connected_at or datetime.now(timezone.utc)
        account.reconnect_required = reconnect_required
        account.last_error = last_error
        await self.session.flush()
        return account

    async def mark_reconnect(self, user_id: int, error: str) -> None:
        account = await self.get_for_user(user_id)
        if account is None:
            return
        account.reconnect_required = True
        account.last_error = error
        await self.session.flush()

    async def mark_synced(self, user_id: int) -> None:
        account = await self.get_for_user(user_id)
        if account is None:
            return
        account.last_synced_at = datetime.now(timezone.utc)
        account.reconnect_required = False
        account.last_error = ""
        await self.session.flush()

    async def delete_for_user(self, user_id: int) -> None:
        await self.session.execute(
            delete(TwitchAccount).where(TwitchAccount.user_id == user_id)
        )
        await self.session.flush()
