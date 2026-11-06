from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import TwitchProfile


class TwitchProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> TwitchProfile | None:
        result = await self.session.execute(
            select(TwitchProfile).order_by(TwitchProfile.id).limit(1)
        )
        return result.scalar_one_or_none()

    async def save(
        self,
        *,
        user_id: str,
        display_name: str,
        profile_image_url: str,
        connected_at: datetime | None,
    ) -> TwitchProfile:
        profile = await self.get()
        if profile is None:
            profile = TwitchProfile()
            self.session.add(profile)

        profile.user_id = user_id
        profile.display_name = display_name
        profile.profile_image_url = profile_image_url
        profile.connected_at = connected_at

        await self.session.flush()
        return profile

    async def clear(self) -> None:
        await self.session.execute(delete(TwitchProfile))
        await self.session.flush()
