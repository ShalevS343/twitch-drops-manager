from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.domain.schemas import GameOut, StreamOut
from app.repositories.streams import StreamRepository

router = APIRouter()


@router.get("/streams", response_model=list[StreamOut])
async def list_streams(
    session: SessionDep,
    game: str | None = Query(default=None),
    live: bool | None = Query(default=True),
) -> list[StreamOut]:
    rows = await StreamRepository(session).list_rows(game_name=game, live=live)

    streams: dict[int, StreamOut] = {}
    campaign_names: dict[int, list[str]] = {}
    for row in rows:
        stream = streams.get(row.id)
        if stream is None:
            stream = StreamOut(
                id=row.id,
                user_login=row.user_login,
                user_name=row.user_name,
                title=row.title,
                viewers=row.viewers,
                language=row.language,
                started_at=row.started_at,
                url=row.url,
                live=row.live,
                game=GameOut(
                    id=row.game_id,
                    name=row.game_name,
                    box_art_url=row.box_art_url,
                    twitch_game_id=row.twitch_game_id,
                    selected=row.selected,
                    # The games endpoint owns campaign_count; this endpoint
                    # never exposed a real value for it.
                    campaign_count=0,
                ),
            )
            streams[row.id] = stream
            campaign_names[row.id] = []

        if row.campaign_name is not None:
            campaign_names[row.id].append(row.campaign_name)

    for stream_id, stream in streams.items():
        stream.matching_campaigns = campaign_names[stream_id]

    return list(streams.values())
