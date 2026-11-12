from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, SessionDep
from app.domain.models import Campaign
from app.domain.schemas import GameOut, GamesUpdate
from app.repositories.games import GameRepository
from app.repositories.user_games import UserGameRepository

router = APIRouter()


def _games_with_counts(
    games, selected_ids: set[int], counts: dict[int, int]
) -> list[GameOut]:
    return [
        GameOut(
            id=game.id,
            name=game.name,
            box_art_url=game.box_art_url,
            twitch_game_id=game.twitch_game_id,
            selected=game.id in selected_ids,
            campaign_count=int(counts.get(game.id, 0)),
        )
        for game in games
    ]


async def _campaign_counts(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(
        select(Campaign.game_id, func.count(Campaign.id)).group_by(Campaign.game_id)
    )
    return {game_id: count for game_id, count in rows.all()}


@router.get("/games", response_model=list[GameOut])
async def list_games(
    session: SessionDep, user: CurrentUserDep
) -> list[GameOut]:
    games = await GameRepository(session).list()
    selected_ids = await UserGameRepository(session).game_ids(user.id)
    counts = await _campaign_counts(session)
    return _games_with_counts(games, selected_ids, counts)


@router.put("/games", response_model=GamesUpdate)
async def update_games(
    payload: GamesUpdate, session: SessionDep, user: CurrentUserDep
) -> GamesUpdate:
    selected = await UserGameRepository(session).replace(user.id, payload.games)
    await session.commit()
    return GamesUpdate(games=[game.name for game in selected])
