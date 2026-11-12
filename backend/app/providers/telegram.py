import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import NotConfiguredError, ProviderError


class TelegramConflictError(ProviderError):
    """Telegram rejected polling because a webhook is configured."""


class TelegramProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._me: dict | None = None
        self._username: str = ""

    @property
    def configured(self) -> bool:
        """A bot token is all the provider needs; each send names its chat."""
        return bool(self.settings.telegram_bot_token)

    @property
    def username(self) -> str:
        """Cached bot username, populated by ``get_me``."""
        return self._username

    async def _post(
        self, method: str, payload: dict, *, timeout: float = 15
    ) -> httpx.Response:
        if not self.configured:
            raise NotConfiguredError("Telegram credentials not configured")

        url = (
            "https://api.telegram.org/bot"
            f"{self.settings.telegram_bot_token}/{method}"
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            # Never include the URL (it contains the bot token) or the raw
            # exception text, which may also embed the URL.
            raise ProviderError(
                f"Telegram request failed ({type(exc).__name__})"
            ) from None

        if response.status_code == 409:
            raise TelegramConflictError(
                "Telegram polling conflict: a webhook is set for this bot. "
                "Call deleteWebhook or disable the worker Telegram poller."
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Telegram request failed ({response.status_code})"
            )
        return response

    async def send(self, message: str, chat_id: str) -> None:
        if not (chat_id or "").strip():
            raise ProviderError("Telegram chat id is not set")

        await self._post(
            "sendMessage",
            {
                "chat_id": chat_id.strip(),
                "text": message,
                "disable_web_page_preview": True,
            },
        )

    async def get_me(self) -> dict:
        """Return the bot identity, caching it for the process lifetime."""
        if self._me is not None:
            return self._me

        response = await self._post("getMe", {})
        result = self._payload(response)
        if not isinstance(result, dict):
            raise ProviderError("Telegram request failed (invalid response)")
        self._username = str(result.get("username") or "").strip()
        self._me = result
        return result

    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        """Long-poll for message updates without ever raising on empty results."""
        payload: dict = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = await self._post(
            "getUpdates", payload, timeout=timeout + 10
        )
        result = self._payload(response)
        if not isinstance(result, list):
            raise ProviderError("Telegram request failed (invalid response)")
        return [item for item in result if isinstance(item, dict)]

    @staticmethod
    def _payload(response: httpx.Response) -> object:
        try:
            body = response.json()
        except ValueError:
            raise ProviderError(
                "Telegram request failed (invalid response)"
            ) from None
        if not isinstance(body, dict) or not body.get("ok"):
            raise ProviderError("Telegram request failed (not ok)")
        return body.get("result")
