from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Game, UserGame


class UserGameRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_games(self, user_id: int) -> list[Game]:
        result = await self.session.execute(
            select(Game)
            .join(UserGame, UserGame.game_id == Game.id)
            .where(UserGame.user_id == user_id)
            .order_by(Game.name)
        )
        return list(result.scalars().all())

    async def selected_names(self, user_id: int) -> list[str]:
        return [game.name for game in await self.list_games(user_id)]

    async def replace(self, user_id: int, names: list[str]) -> list[Game]:
        wanted: dict[str, str] = {}
        for raw in names:
            name = raw.strip()
            if name:
                wanted.setdefault(name.casefold(), name)

        games = list(
            (
                await self.session.execute(select(Game).order_by(Game.name))
            ).scalars().all()
        )
        by_name = {game.name.casefold(): game for game in games}

        for key, name in wanted.items():
            if key not in by_name:
                game = Game(name=name, selected=False)
                self.session.add(game)
                by_name[key] = game
        await self.session.flush()

        await self.session.execute(
            delete(UserGame).where(UserGame.user_id == user_id)
        )
        selected = [by_name[key] for key in sorted(wanted)]
        for game in selected:
            self.session.add(UserGame(user_id=user_id, game_id=game.id))
        await self.session.flush()
        return selected

    async def seed_defaults(self, user_id: int, names: list[str]) -> list[Game]:
        existing = await self.list_games(user_id)
        if existing:
            return existing
        return await self.replace(user_id, names)

    async def delete_for_user(self, user_id: int) -> None:
        await self.session.execute(
            delete(UserGame).where(UserGame.user_id == user_id)
        )
        await self.session.flush()
