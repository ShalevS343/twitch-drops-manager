from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.domain.parsing import campaign_gql_id_from_external_id
from app.domain.schemas import GameOut, StreamOut
from app.repositories.campaign_completions import CampaignCompletionRepository
from app.repositories.streams import StreamRepository

router = APIRouter()


@router.get("/streams", response_model=list[StreamOut])
async def list_streams(
    session: SessionDep,
    game: str | None = Query(default=None),
    live: bool | None = Query(default=True),
) -> list[StreamOut]:
    rows = await StreamRepository(session).list_rows(game_name=game, live=live)
    completed_ids = {
        row.campaign_gql_id
        for row in await CampaignCompletionRepository(session).list()
    }

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

        if row.campaign_name is not None and row.campaign_external_id is not None:
            gql_id = campaign_gql_id_from_external_id(row.campaign_external_id)
            if gql_id not in completed_ids:
                campaign_names[row.id].append(row.campaign_name)

    result: list[StreamOut] = []
    for stream_id, stream in streams.items():
        stream.matching_campaigns = campaign_names[stream_id]
        # Only keep streams that still advance an uncompleted campaign.
        if stream.matching_campaigns:
            result.append(stream)

    return result
