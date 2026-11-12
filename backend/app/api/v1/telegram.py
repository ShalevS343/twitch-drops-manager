from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, TelegramLinkServiceDep
from app.core.exceptions import NotConfiguredError, ProviderError
from app.core.rate_limit import enforce_user_action_limit
from app.domain.schemas import TelegramLinkOut

router = APIRouter()


@router.post("/telegram/link", response_model=TelegramLinkOut)
async def create_telegram_link(
    user: CurrentUserDep, service: TelegramLinkServiceDep
) -> TelegramLinkOut:
    enforce_user_action_limit("telegram.link", user.id)
    try:
        return await service.create_link(user.id)
    except NotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc


@router.post("/telegram/unlink")
async def unlink_telegram(user: CurrentUserDep, service: TelegramLinkServiceDep) -> dict:
    enforce_user_action_limit("telegram.unlink", user.id)
    try:
        await service.unlink(user.id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    return {"unlinked": True}
