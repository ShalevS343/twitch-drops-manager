from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import TelegramDep
from app.core.exceptions import NotConfiguredError, ProviderError
from app.core.security import require_api_token

router = APIRouter()


@router.post(
    "/notifications/test",
    dependencies=[Depends(require_api_token)],
)
async def test_notification(telegram: TelegramDep) -> dict:
    if not telegram.configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram credentials not configured",
        )

    try:
        await telegram.send("Twitch Drops Manager: Telegram test message.")
    except (NotConfiguredError, ProviderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return {"sent": True}
