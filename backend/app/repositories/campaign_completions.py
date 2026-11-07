from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CampaignCompletion


class CampaignCompletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[CampaignCompletion]:
        result = await self.session.execute(
            select(CampaignCompletion).order_by(CampaignCompletion.id)
        )
        return list(result.scalars().all())

    async def upsert_many(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return

        ids = {str(item["campaign_gql_id"]) for item in items}
        result = await self.session.execute(
            select(CampaignCompletion.campaign_gql_id).where(
                CampaignCompletion.campaign_gql_id.in_(ids)
            )
        )
        existing = set(result.scalars().all())

        for item in items:
            campaign_gql_id = str(item["campaign_gql_id"])
            if campaign_gql_id in existing:
                continue
            self.session.add(
                CampaignCompletion(
                    campaign_gql_id=campaign_gql_id,
                    campaign_name=str(item.get("campaign_name") or ""),
                    game_name=str(item.get("game_name") or ""),
                )
            )
        await self.session.flush()
