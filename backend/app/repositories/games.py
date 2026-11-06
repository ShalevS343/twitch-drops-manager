from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Game


class GameRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Game))
        return int(result.scalar_one())

    async def list(self) -> list[Game]:
        result = await self.session.execute(select(Game).order_by(Game.name))
        return list(result.scalars().all())

    async def list_selected(self) -> list[Game]:
        result = await self.session.execute(
            select(Game).where(Game.selected.is_(True)).order_by(Game.name)
        )
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> Game | None:
        result = await self.session.execute(
            select(Game).where(func.lower(Game.name) == name.strip().lower())
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        name: str,
        box_art_url: str = "",
        twitch_game_id: str | None = None,
    ) -> Game:
        game = await self.get_by_name(name)
        if game is None:
            game = Game(
                name=name.strip(),
                box_art_url=box_art_url,
                twitch_game_id=twitch_game_id,
            )
            self.session.add(game)
            await self.session.flush()
            return game

        if box_art_url:
            game.box_art_url = box_art_url
        if twitch_game_id:
            game.twitch_game_id = twitch_game_id
        return game

    async def set_selected(self, names: list[str]) -> list[Game]:
        wanted: dict[str, str] = {}
        for raw in names:
            name = raw.strip()
            if name:
                wanted.setdefault(name.casefold(), name)

        games = await self.list()
        by_name = {game.name.casefold(): game for game in games}

        # Allow tracking a game before it has a campaign (or before it appears
        # in the catalog at all). The scan fills in Twitch metadata later.
        for key, name in wanted.items():
            if key not in by_name:
                game = Game(name=name, selected=True)
                self.session.add(game)
                by_name[key] = game

        for game in games:
            game.selected = game.name.casefold() in wanted

        await self.session.flush()
        return sorted(
            (game for game in by_name.values() if game.selected),
            key=lambda game: game.name.casefold(),
        )

    async def select_defaults(self, names: list[str]) -> None:
        await self.set_selected(names)
