"""Progress and profile services use each account's issuing client id."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.profile_service import ProfileService
from app.services.progress_service import ProgressService
from tests.support import connect_account, create_user, future, make_engine

SMART_TV = "smart-tv-client"
ANDROID = "android-client"


class InventoryProvider:
    def __init__(self):
        self.calls = []

    async def fetch_inventory(self, access_token, client_id=""):
        self.calls.append((access_token, client_id))
        return {"dropCampaignsInProgress": []}


class ProfileProvider:
    def __init__(self):
        self.calls = []

    async def fetch_profile(self, access_token, user_id="", client_id=""):
        self.calls.append((access_token, user_id, client_id))
        return {"displayName": "Viewer", "profileImageURL": "avatar"}


class NoTelegram:
    configured = False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_client_id", "expected"),
    [(SMART_TV, SMART_TV), ("", ANDROID)],
)
async def test_progress_uses_account_client_id_with_android_fallback(
    stored_client_id, expected
):
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session)
        await connect_account(
            session,
            user,
            access_token="token",
            expires_at=future(),
            client_id=stored_client_id,
        )
        await session.commit()

        provider = InventoryProvider()
        await ProgressService(
            session,
            user.id,
            Settings(
                _env_file=None,
                default_games="",
                twitch_gql_client_id=ANDROID,
            ),
            provider,
            NoTelegram(),
        ).run()

        assert provider.calls == [("token", expected)]

    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_client_id", "expected"),
    [(SMART_TV, SMART_TV), ("", ANDROID)],
)
async def test_profile_refresh_uses_account_client_id_with_android_fallback(
    stored_client_id, expected, monkeypatch
):
    monkeypatch.setattr(
        "app.services.profile_service.get_settings",
        lambda: Settings(
            _env_file=None,
            twitch_gql_client_id=ANDROID,
            twitch_device_client_id=ANDROID,
        ),
    )
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session)
        await connect_account(
            session,
            user,
            access_token="token",
            expires_at=future(),
            client_id=stored_client_id,
        )
        await session.commit()

        provider = ProfileProvider()
        service = ProfileService()
        await service.refresh(
            user.id,
            provider=provider,
            session_factory=factory,
        )

        assert provider.calls == [("token", user.twitch_user_id, expected)]

    await engine.dispose()
