from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, TelegramDep
from app.core.exceptions import NotConfiguredError, ProviderError

router = APIRouter()


@router.post("/notifications/test")
async def test_notification(user: CurrentUserDep, telegram: TelegramDep) -> dict:
    if not telegram.configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram credentials not configured",
        )
    if not user.telegram_enabled or not user.telegram_chat_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram is not enabled for this account",
        )

    try:
        await telegram.send(
            "Twitch Drops Manager: Telegram test message.",
            user.telegram_chat_id.strip(),
        )
    except (NotConfiguredError, ProviderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return {"sent": True}
