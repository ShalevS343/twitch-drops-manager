from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    Campaign,
    Game,
    Stream,
    StreamCampaignMatch,
    UserGame,
)


class StreamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_rows(
        self,
        user_id: int,
        game_name: str | None = None,
        live: bool | None = True,
    ) -> list[Any]:
        """Return flat stream/game/campaign-name rows for the streams endpoint."""
        stmt = (
            select(
                Stream.id,
                Stream.user_login,
                Stream.user_name,
                Stream.title,
                Stream.viewers,
                Stream.language,
                Stream.started_at,
                Stream.url,
                Stream.live,
                Game.id.label("game_id"),
                Game.name.label("game_name"),
                Game.box_art_url,
                Game.twitch_game_id,
                UserGame.id.isnot(None).label("selected"),
                Campaign.external_id.label("campaign_external_id"),
                Campaign.name.label("campaign_name"),
            )
            .join(Game, Stream.game_id == Game.id)
            .outerjoin(
                UserGame,
                (UserGame.game_id == Game.id) & (UserGame.user_id == user_id),
            )
            .outerjoin(StreamCampaignMatch, StreamCampaignMatch.stream_id == Stream.id)
            .outerjoin(Campaign, StreamCampaignMatch.campaign_id == Campaign.id)
            .order_by(Stream.viewers.desc())
        )

        if live is not None:
            stmt = stmt.where(Stream.live.is_(live))
        if game_name:
            stmt = stmt.where(func.lower(Game.name) == game_name.lower())
        stmt = stmt.where(
            Game.id.in_(
                select(UserGame.game_id).where(UserGame.user_id == user_id)
            )
        )

        result = await self.session.execute(stmt)
        return list(result.all())

    async def list_watch_queue_rows(self) -> list[Any]:
        """Return flat rows for live streams with their matched campaigns."""
        stmt = (
            select(
                Stream.id.label("stream_id"),
                Stream.user_login,
                Stream.user_name,
                Stream.title,
                Stream.viewers,
                Stream.language,
                Stream.url,
                Game.name.label("game_name"),
                Game.box_art_url.label("game_box_art_url"),
                Campaign.id.label("campaign_id"),
                Campaign.external_id,
                Campaign.name.label("campaign_name"),
                Campaign.ends_at,
            )
            .join(Game, Stream.game_id == Game.id)
            .join(StreamCampaignMatch, StreamCampaignMatch.stream_id == Stream.id)
            .join(Campaign, StreamCampaignMatch.campaign_id == Campaign.id)
            .where(Stream.live.is_(True))
            .order_by(Stream.viewers.desc(), Stream.id, Campaign.id)
        )

        result = await self.session.execute(stmt)
        return list(result.all())

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
