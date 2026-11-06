import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import NotConfiguredError, ProviderError


class TelegramProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    async def send(self, message: str) -> None:
        if not self.configured:
            raise NotConfiguredError("Telegram credentials not configured")

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": self.settings.telegram_chat_id,
                        "text": message,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Telegram request failed: {exc}") from exc
