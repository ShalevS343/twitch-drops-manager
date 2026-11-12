from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Campaign, UserCampaignStart


class CampaignStartRepository:
    """Pending campaign-start notices for one user."""

    def __init__(self, session: AsyncSession, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    async def add_pending(self, items: list[dict[str, Any]]) -> None:
        """Insert start events for this user, ignoring ones already recorded."""
        for item in items:
            try:
                async with self.session.begin_nested():
                    self.session.add(
                        UserCampaignStart(
                            user_id=self.user_id,
                            external_id=str(item["external_id"]),
                        )
                    )
                    await self.session.flush()
            except IntegrityError:
                # Another scan already recorded this start for this user.
                continue

    async def pending(self) -> list[tuple[UserCampaignStart, Campaign]]:
        result = await self.session.execute(
            select(UserCampaignStart, Campaign)
            .join(Campaign, Campaign.external_id == UserCampaignStart.external_id)
            .where(UserCampaignStart.user_id == self.user_id)
            .order_by(UserCampaignStart.id)
        )
        return [(start, campaign) for start, campaign in result.all()]

    async def delete(self, external_ids: set[str]) -> None:
        if not external_ids:
            return
        await self.session.execute(
            delete(UserCampaignStart).where(
                UserCampaignStart.user_id == self.user_id,
                UserCampaignStart.external_id.in_(external_ids),
            )
        )

    @staticmethod
    async def delete_all_orphans(session: AsyncSession) -> None:
        """Remove start rows whose campaign no longer exists (all users)."""
        campaign_ids = select(Campaign.external_id)
        await session.execute(
            delete(UserCampaignStart).where(
                UserCampaignStart.external_id.not_in(campaign_ids)
            )
        )
