import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import NotConfiguredError, ProviderError


class TelegramProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        """A bot token is all the provider needs; each send names its chat."""
        return bool(self.settings.telegram_bot_token)

    async def send(self, message: str, chat_id: str) -> None:
        if not self.configured:
            raise NotConfiguredError("Telegram credentials not configured")
        if not (chat_id or "").strip():
            raise ProviderError("Telegram chat id is not set")

        url = (
            "https://api.telegram.org/bot"
            f"{self.settings.telegram_bot_token}/sendMessage"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": chat_id.strip(),
                        "text": message,
                        "disable_web_page_preview": True,
                    },
                )
        except httpx.HTTPError as exc:
            # Never include the URL (it contains the bot token) or the raw
            # exception text, which may also embed the URL.
            raise ProviderError(
                f"Telegram request failed ({type(exc).__name__})"
            ) from None

        if response.status_code >= 400:
            raise ProviderError(
                f"Telegram request failed ({response.status_code})"
            )
