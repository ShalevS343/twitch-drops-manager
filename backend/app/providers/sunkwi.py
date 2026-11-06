import asyncio
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import ProviderError


class SunkwiProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    async def fetch_games(self) -> dict[str, Any]:
        async with self._lock:
            now = time.monotonic()
            if self._cache is not None and now - self._cached_at < self.settings.drops_cache_seconds:
                return self._cache

            headers = {}
            if self.settings.drops_api_key:
                headers["X-API-Key"] = self.settings.drops_api_key

            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get(self.settings.sunkwi_url, headers=headers)
                    response.raise_for_status()
                    payload = response.json()
            except httpx.HTTPError as exc:
                raise ProviderError(f"Drops API request failed: {exc}") from exc

            games = payload.get("games") if isinstance(payload, dict) else None
            if not isinstance(games, list):
                raise ProviderError("Invalid Drops API response: expected a games list")

            self._cache = payload
            self._cached_at = now
            return payload
