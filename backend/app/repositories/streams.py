from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models import Game, Stream, StreamCampaignMatch


class StreamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self, game_name: str | None = None, live: bool | None = True
    ) -> list[Stream]:
        stmt = (
            select(Stream)
            .options(
                selectinload(Stream.game),
                selectinload(Stream.matches).selectinload(StreamCampaignMatch.campaign),
            )
            .order_by(Stream.viewers.desc())
        )

        if live is not None:
            stmt = stmt.where(Stream.live.is_(live))
        if game_name:
            stmt = stmt.join(Game).where(func.lower(Game.name) == game_name.lower())

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def replace(self, records: list[dict[str, Any]]) -> None:
        await self.session.execute(delete(StreamCampaignMatch))
        await self.session.execute(delete(Stream))
        await self.session.flush()

        for record in records:
            stream = Stream(
                user_login=record["user_login"],
                user_name=record["user_name"],
                game_id=record["game_id"],
                title=record["title"],
                viewers=record["viewers"],
                language=record["language"],
                started_at=record["started_at"],
                url=record["url"],
                live=True,
            )
            self.session.add(stream)
            await self.session.flush()

            for campaign_id in record["campaign_ids"]:
                self.session.add(
                    StreamCampaignMatch(
                        stream_id=stream.id,
                        campaign_id=campaign_id,
                        eligibility=record["eligibility"],
                    )
                )

        await self.session.flush()
