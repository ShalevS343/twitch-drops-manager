from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.core.security import require_api_token
from app.domain.models import Campaign
from app.domain.schemas import GameOut, GamesUpdate
from app.repositories.games import GameRepository

router = APIRouter()


async def _games_with_counts(session: AsyncSession) -> list[GameOut]:
    games = await GameRepository(session).list()
    rows = await session.execute(
        select(Campaign.game_id, func.count(Campaign.id)).group_by(Campaign.game_id)
    )
    counts = {game_id: count for game_id, count in rows.all()}

    return [
        GameOut(
            id=game.id,
            name=game.name,
            box_art_url=game.box_art_url,
            twitch_game_id=game.twitch_game_id,
            selected=game.selected,
            campaign_count=int(counts.get(game.id, 0)),
        )
        for game in games
    ]


@router.get("/games", response_model=list[GameOut])
async def list_games(session: SessionDep) -> list[GameOut]:
    return await _games_with_counts(session)


@router.put(
    "/games",
    response_model=GamesUpdate,
    dependencies=[Depends(require_api_token)],
)
async def update_games(payload: GamesUpdate, session: SessionDep) -> GamesUpdate:
    selected = await GameRepository(session).set_selected(payload.games)
    await session.commit()
    return GamesUpdate(games=[game.name for game in selected])
