from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.domain.schemas import StreamOut
from app.repositories.streams import StreamRepository

router = APIRouter()


@router.get("/streams", response_model=list[StreamOut])
async def list_streams(
    session: SessionDep,
    game: str | None = Query(default=None),
    live: bool | None = Query(default=True),
) -> list[StreamOut]:
    streams = await StreamRepository(session).list(game_name=game, live=live)
    return [StreamOut.model_validate(stream) for stream in streams]
