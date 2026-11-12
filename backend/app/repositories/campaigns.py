from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models import Campaign, Game, Reward


class CampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        game_name: str | None = None,
        status: str | None = None,
        active_only: bool = False,
        game_ids: set[int] | None = None,
    ) -> list[Campaign]:
        stmt = (
            select(Campaign)
            .options(selectinload(Campaign.game), selectinload(Campaign.rewards))
            .order_by(Campaign.name)
            .join(Game)
        )

        if game_name:
            stmt = stmt.where(func.lower(Game.name) == game_name.lower())
        if game_ids is not None:
            if not game_ids:
                return []
            stmt = stmt.where(Game.id.in_(game_ids))

        if active_only:
            stmt = stmt.where(Campaign.status == "ACTIVE")
        elif status:
            stmt = stmt.where(Campaign.status == status.upper())

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_active_for_games(self, names: set[str]) -> list[Campaign]:
        if not names:
            return []

        stmt = (
            select(Campaign)
            .join(Game)
            .options(selectinload(Campaign.game), selectinload(Campaign.rewards))
            .where(func.lower(Game.name).in_([name.lower() for name in names]))
            .where(Campaign.status == "ACTIVE")
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def statuses_by_external_ids(self, external_ids: set[str]) -> dict[str, str]:
        if not external_ids:
            return {}

        result = await self.session.execute(
            select(Campaign.external_id, Campaign.status).where(
                Campaign.external_id.in_(external_ids)
            )
        )
        return {external_id: status for external_id, status in result.all()}


    async def by_ids(self, ids: set[int]) -> list[Campaign]:
        if not ids:
            return []

        result = await self.session.execute(
            select(Campaign).where(Campaign.id.in_(ids))
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[Campaign]:
        result = await self.session.execute(select(Campaign).order_by(Campaign.id))
        return list(result.scalars().all())

    async def upsert_many(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return

        external_ids = [item["external_id"] for item in items]
        existing: dict[str, Campaign] = {}
        for index in range(0, len(external_ids), 500):
            chunk = external_ids[index : index + 500]
            result = await self.session.execute(
                select(Campaign)
                .options(selectinload(Campaign.rewards))
                .where(Campaign.external_id.in_(chunk))
            )
            existing.update(
                {campaign.external_id: campaign for campaign in result.scalars().all()}
            )

        for item in items:
            campaign = existing.get(item["external_id"])
            if campaign is None:
                campaign = Campaign(external_id=item["external_id"])
                self.session.add(campaign)
                existing[item["external_id"]] = campaign

            campaign.game_id = item["game_id"]
            campaign.name = item["name"]
            campaign.status = item["status"]
            campaign.starts_at = item["starts_at"]
            campaign.ends_at = item["ends_at"]
            campaign.details_url = item["details_url"]
            campaign.owner_name = item["owner_name"]
            campaign.allow = item["allow"]
            campaign.raw = item["raw"]

            campaign.rewards.clear()
            for reward in item["rewards"]:
                campaign.rewards.append(Reward(**reward))

        await self.session.flush()

    async def delete_stale(self, keep_external_ids: set[str]) -> None:
        result = await self.session.execute(select(Campaign.id, Campaign.external_id))
        stale_ids = [
            campaign_id
            for campaign_id, external_id in result.all()
            if external_id not in keep_external_ids
        ]

        for index in range(0, len(stale_ids), 500):
            chunk = stale_ids[index : index + 500]
            await self.session.execute(delete(Campaign).where(Campaign.id.in_(chunk)))
