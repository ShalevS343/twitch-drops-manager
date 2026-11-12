"""Bounds on the user-controlled games catalog (M-9)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.domain.models import Game
from app.domain.schemas import MAX_GAME_NAME_LENGTH, MAX_GAMES, GamesUpdate
from app.repositories.user_games import UserGameRepository
from tests.support import create_user, make_engine


def test_games_update_rejects_more_than_the_cap():
    with pytest.raises(ValidationError):
        GamesUpdate(games=[f"game-{index}" for index in range(MAX_GAMES + 1)])

    assert len(GamesUpdate(games=[f"game-{index}" for index in range(MAX_GAMES)]).games) == 50


def test_games_update_rejects_overlong_and_blank_names():
    with pytest.raises(ValidationError):
        GamesUpdate(games=["x" * (MAX_GAME_NAME_LENGTH + 1)])

    with pytest.raises(ValidationError):
        GamesUpdate(games=["   "])

    with pytest.raises(ValidationError):
        GamesUpdate(games=[""])


def test_games_update_strips_names():
    assert GamesUpdate(games=["  Rust  "]).games == ["Rust"]


@pytest.mark.asyncio
async def test_repository_refuses_unbounded_or_overlong_games():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        repo = UserGameRepository(session)

        with pytest.raises(ValueError):
            await repo.replace(
                user.id, [f"game-{index}" for index in range(MAX_GAMES + 1)]
            )

        with pytest.raises(ValueError):
            await repo.replace(user.id, ["x" * (MAX_GAME_NAME_LENGTH + 1)])

        game_count = await session.scalar(select(func.count()).select_from(Game))
        assert game_count == 0

    await engine.dispose()
