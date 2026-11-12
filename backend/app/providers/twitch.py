import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import NotConfiguredError, ProviderError

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_URL = "https://api.twitch.tv/helix/"


class TwitchProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._token: str | None = None
        self._expires_at = 0.0

    @property
    def ready(self) -> bool:
        return bool(self.settings.twitch_client_id and self.settings.twitch_client_secret)

    async def _get_token(self) -> str:
        if not self.ready:
            raise NotConfiguredError("Twitch API credentials not configured")
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    TOKEN_URL,
                    data={
                        "client_id": self.settings.twitch_client_id,
                        "client_secret": self.settings.twitch_client_secret,
                        "grant_type": "client_credentials",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            # Never echo the URL, request body, or upstream response: the body
            # carries the client secret and old builds put it in the query.
            raise ProviderError(
                f"Twitch token request failed ({type(exc).__name__})"
            ) from None

        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def _request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = await self._get_token()
        headers = {
            "Client-Id": self.settings.twitch_client_id,
            "Authorization": f"Bearer {token}",
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    HELIX_URL + endpoint, headers=headers, params=params or {}
                )
                if response.status_code == 401:
                    self._token = None
                    token = await self._get_token()
                    headers["Authorization"] = f"Bearer {token}"
                    response = await client.get(
                        HELIX_URL + endpoint, headers=headers, params=params or {}
                    )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Twitch API request failed ({type(exc).__name__})"
            ) from None

    async def get_streams(self, game_id: str, max_pages: int = 5) -> list[dict[str, Any]]:
        streams: list[dict[str, Any]] = []
        cursor: str | None = None

        for _ in range(max_pages):
            params = {"game_id": game_id, "first": 100}
            if cursor:
                params["after"] = cursor

            payload = await self._request("streams", params)
            page = payload.get("data")
            if not isinstance(page, list) or not page:
                break

            streams.extend(item for item in page if isinstance(item, dict))
            cursor = (payload.get("pagination") or {}).get("cursor")
            if not cursor:
                break

        return streams
