from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.domain.parsing import campaign_gql_id_from_external_id
from app.domain.schemas import CampaignOut
from app.repositories.campaign_completions import CampaignCompletionRepository
from app.repositories.campaigns import CampaignRepository

router = APIRouter()


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    session: SessionDep,
    game: str | None = Query(default=None),
    status: str | None = Query(default=None),
    active_only: bool = Query(default=False),
) -> list[CampaignOut]:
    campaigns = await CampaignRepository(session).list(
        game_name=game, status=status, active_only=active_only
    )
    completed_ids = {
        row.campaign_gql_id
        for row in await CampaignCompletionRepository(session).list()
    }
    return [
        CampaignOut.model_validate(campaign).model_copy(
            update={
                "completed": campaign_gql_id_from_external_id(
                    campaign.external_id
                )
                in completed_ids
            }
        )
        for campaign in campaigns
    ]
