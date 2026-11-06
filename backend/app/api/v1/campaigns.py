from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.domain.schemas import CampaignOut
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
    return [CampaignOut.model_validate(campaign) for campaign in campaigns]
