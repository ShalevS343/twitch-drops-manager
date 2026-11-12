"""Per-user Twitch profile refresh tasks."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.core.db import SessionLocal
from app.core.exceptions import (
    NotConfiguredError,
    ProviderError,
    ReconnectRequiredError,
)
from app.repositories.twitch_accounts import TwitchAccountRepository
from app.repositories.users import UserRepository
from app.services.factory import get_twitch_user_provider

logger = logging.getLogger(__name__)

RECONNECT_MESSAGE = "Twitch login expired; reconnect your account"


class ProfileService:
    """Fetch and persist one user's Twitch profile without blocking requests."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self._inflight: set[int] = set()

    async def refresh(
        self,
        user_id: int,
        provider=None,
        session_factory=None,
    ) -> None:
        factory = session_factory or SessionLocal
        provider = provider or get_twitch_user_provider()

        async with factory() as session:
            account = await TwitchAccountRepository(session).get_for_user(user_id)
            user = await UserRepository(session).get(user_id)
            if account is None or user is None:
                return

            display_name = user.display_name
            profile_image_url = user.profile_image_url
            try:
                profile = await provider.fetch_profile(
                    account.access_token, user.twitch_user_id
                )
                display_name = str(profile.get("displayName") or display_name)
                profile_image_url = str(profile.get("profileImageURL") or "")
            except ReconnectRequiredError:
                await TwitchAccountRepository(session).mark_reconnect(
                    user_id, RECONNECT_MESSAGE
                )
                display_name = display_name or user.login or user.twitch_user_id
            except (NotConfiguredError, ProviderError):
                # Mark the profile as checked so a failing provider is not
                # retried on every status poll.
                display_name = display_name or user.login or user.twitch_user_id

            await UserRepository(session).update_profile(
                user,
                login=user.login,
                display_name=display_name,
                profile_image_url=profile_image_url,
            )
            await session.commit()

    async def warm_up(self, session_factory=None) -> None:
        """Schedule a refresh for every connected user with no profile."""
        factory = session_factory or SessionLocal
        async with factory() as session:
            user_ids = await UserRepository(session).list_ids_missing_profile()

        for user_id in user_ids:
            self.schedule(user_id)

    def schedule(self, user_id: int, provider=None) -> asyncio.Task[None] | None:
        """Schedule one background refresh per user, or None if already busy."""
        if user_id in self._inflight:
            return None

        self._inflight.add(user_id)
        try:
            task = asyncio.create_task(self._run(user_id, provider))
        except RuntimeError:
            self._inflight.discard(user_id)
            return None

        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run(self, user_id: int, provider=None) -> None:
        try:
            await self.refresh(user_id, provider)
        except Exception as exc:  # noqa: BLE001 - background best effort
            logger.error(
                "Profile refresh failed for user %s (%s)",
                user_id,
                type(exc).__name__,
            )
        finally:
            self._inflight.discard(user_id)

    async def shutdown(self) -> None:
        """Cancel in-flight background profile fetches during shutdown."""
        while self._tasks:
            tasks = list(self._tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._inflight.clear()


@lru_cache
def get_profile_service() -> ProfileService:
    return ProfileService()
