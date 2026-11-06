from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import TwitchAuth


class TwitchAuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> TwitchAuth | None:
        result = await self.session.execute(
            select(TwitchAuth).order_by(TwitchAuth.id).limit(1)
        )
        return result.scalar_one_or_none()

    async def save(
        self,
        *,
        user_id: str,
        login: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime | None,
    ) -> TwitchAuth:
        auth = await self.get()
        if auth is None:
            auth = TwitchAuth()
            self.session.add(auth)

        auth.user_id = user_id
        auth.login = login
        auth.access_token = access_token
        auth.refresh_token = refresh_token
        auth.expires_at = expires_at

        await self.session.flush()
        return auth

    async def clear(self) -> None:
        await self.session.execute(delete(TwitchAuth))
        await self.session.flush()
