from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, SessionDep
from app.domain.parsing import campaign_gql_id_from_external_id
from app.domain.schemas import CampaignOut
from app.repositories.campaign_completions import CampaignCompletionRepository
from app.repositories.campaigns import CampaignRepository
from app.repositories.user_games import UserGameRepository

router = APIRouter()


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    session: SessionDep,
    user: CurrentUserDep,
    game: str | None = Query(default=None),
    status: str | None = Query(default=None),
    active_only: bool = Query(default=False),
) -> list[CampaignOut]:
    selected_ids = await UserGameRepository(session).game_ids(user.id)
    campaigns = await CampaignRepository(session).list(
        game_name=game,
        status=status,
        active_only=active_only,
        game_ids=selected_ids,
    )
    completed_ids = {
        row.campaign_gql_id
        for row in await CampaignCompletionRepository(session, user.id).list()
    }

    result: list[CampaignOut] = []
    for campaign in campaigns:
        out = CampaignOut.model_validate(campaign).model_copy(
            update={
                "completed": campaign_gql_id_from_external_id(
                    campaign.external_id
                )
                in completed_ids
            }
        )
        out.game.selected = campaign.game_id in selected_ids
        result.append(out)
    return result
