from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, TelegramLinkServiceDep
from app.core.exceptions import NotConfiguredError, ProviderError
from app.core.rate_limit import get_auth_limiter
from app.domain.schemas import TelegramLinkOut

router = APIRouter()


@router.post("/telegram/link", response_model=TelegramLinkOut)
async def create_telegram_link(
    user: CurrentUserDep, service: TelegramLinkServiceDep
) -> TelegramLinkOut:
    limiter = get_auth_limiter()
    key = f"telegram-link:{user.id}"
    if not limiter.check(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many link requests; try again later",
            headers={"Retry-After": str(limiter.retry_after(key))},
        )

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
    await service.unlink(user.id)
    return {"unlinked": True}
