import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import ProviderError

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_SECONDS = 300


class SunkwiProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._retry_at = 0.0
        self._lock = asyncio.Lock()
        self._cache_path = self._resolve_cache_path()
        self._load_disk_cache()

    def _resolve_cache_path(self) -> Path | None:
        url = self.settings.database_url
        if not url.startswith("sqlite"):
            return None
        path = url.split(":///", 1)[-1]
        if not path or path == ":memory:":
            return None
        return Path(path).parent / "sunkwi_cache.json"

    def _load_disk_cache(self) -> None:
        if self._cache_path is None or not self._cache_path.exists():
            return
        try:
            payload = json.loads(self._cache_path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Could not read cached Drops API payload: %s", exc)
            return

        if isinstance(payload, dict) and isinstance(payload.get("games"), list):
            self._cache = payload
            # Force a fresh attempt on startup; the disk copy is only a fallback.
            self._cached_at = 0.0

    def _save_disk_cache(self, payload: dict[str, Any]) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), "utf-8")
            os.replace(tmp, self._cache_path)
        except OSError as exc:
            logger.warning("Could not write cached Drops API payload: %s", exc)

    def _remember(self, payload: dict[str, Any], reset_seconds: int | None) -> None:
        self._cache = payload
        self._cached_at = time.monotonic()

        # The API allows one request per window (currently 300s). Respect its
        # own reset header so a manual scan doesn't immediately burn the slot.
        cooldown = reset_seconds or self.settings.drops_cache_seconds
        self._retry_at = time.monotonic() + max(1, cooldown)

    def _fallback(self) -> dict[str, Any] | None:
        """Return the newest cached payload, reloading the shared disk copy."""
        if self._cache is None:
            self._load_disk_cache()
        return self._cache

    @staticmethod
    def _reset_seconds(response: httpx.Response) -> int | None:
        for header in ("X-RateLimit-Reset", "RateLimit-Reset", "Retry-After"):
            value = response.headers.get(header)
            if value and value.strip().isdigit():
                return int(value.strip())
        return None

    async def fetch_games(self) -> dict[str, Any]:
        async with self._lock:
            now = time.monotonic()

            if self._cache is not None and now < self._retry_at:
                logger.info(
                    "Drops API cooling down for %.0fs; serving cached data",
                    self._retry_at - now,
                )
                return self._cache

            if (
                self._cache is not None
                and now - self._cached_at < self.settings.drops_cache_seconds
            ):
                return self._cache

            headers = {}
            if self.settings.drops_api_key:
                headers["X-API-Key"] = self.settings.drops_api_key

            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get(self.settings.sunkwi_url, headers=headers)

                    if response.status_code == 429:
                        reset = self._reset_seconds(response)
                        self._retry_at = time.monotonic() + (
                            reset or DEFAULT_RATE_LIMIT_SECONDS
                        )
                        cached = self._fallback()
                        if cached is not None:
                            logger.warning(
                                "Drops API rate limited; serving cached data (%.0fs)",
                                self._retry_at - time.monotonic(),
                            )
                            return cached
                        raise ProviderError(
                            "Drops API rate limited; try again in "
                            f"{reset or DEFAULT_RATE_LIMIT_SECONDS}s"
                        )

                    response.raise_for_status()
                    payload = response.json()
            except httpx.HTTPStatusError as exc:
                cached = self._fallback()
                if exc.response.status_code >= 500 and cached is not None:
                    logger.warning(
                        "Drops API returned %s; serving cached data",
                        exc.response.status_code,
                    )
                    return cached
                raise ProviderError(f"Drops API request failed: {exc}") from exc
            except httpx.HTTPError as exc:
                cached = self._fallback()
                if cached is not None:
                    logger.warning("Drops API unreachable; serving cached data: %s", exc)
                    return cached
                raise ProviderError(f"Drops API request failed: {exc}") from exc

            games = payload.get("games") if isinstance(payload, dict) else None
            if not isinstance(games, list):
                cached = self._fallback()
                if cached is not None:
                    logger.warning("Invalid Drops API response; serving cached data")
                    return cached
                raise ProviderError("Invalid Drops API response: expected a games list")

            self._remember(payload, self._reset_seconds(response))
            return payload
