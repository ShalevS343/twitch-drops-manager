from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Campaign, CampaignStart


class CampaignStartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_pending(self, items: list[dict[str, Any]]) -> None:
        """Insert start events, ignoring ones already recorded."""
        for item in items:
            try:
                async with self.session.begin_nested():
                    self.session.add(
                        CampaignStart(external_id=str(item["external_id"]))
                    )
                    await self.session.flush()
            except IntegrityError:
                # Another scan already recorded this start.
                continue

    async def pending(self) -> list[tuple[CampaignStart, Campaign]]:
        result = await self.session.execute(
            select(CampaignStart, Campaign)
            .join(Campaign, Campaign.external_id == CampaignStart.external_id)
            .order_by(CampaignStart.id)
        )
        return [(start, campaign) for start, campaign in result.all()]

    async def delete(self, external_ids: set[str]) -> None:
        if not external_ids:
            return
        await self.session.execute(
            delete(CampaignStart).where(CampaignStart.external_id.in_(external_ids))
        )

    async def delete_orphans(self) -> None:
        campaign_ids = select(Campaign.external_id)
        await self.session.execute(
            delete(CampaignStart).where(
                CampaignStart.external_id.not_in(campaign_ids)
            )
        )
