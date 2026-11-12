from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.progress import twitch_status
from app.api.v1.status import status
from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.services.profile_service import ProfileService
from tests.support import (
    connect_account,
    create_user,
    future,
    make_engine,
)


class FakeTwitchUserProvider:
    def __init__(self, profile=None, error=None):
        self.profile = profile or {}
        self.error = error
        self.calls = []

    async def fetch_profile(self, access_token, user_id=""):
        self.calls.append((access_token, user_id))
        if self.error is not None:
            raise self.error
        return self.profile


async def _session():
    return await make_engine()


@pytest.mark.asyncio
async def test_status_exposes_polling_settings(monkeypatch):
    engine, factory = await _session()
    settings = Settings(
        _env_file=None,
        poll_seconds=900,
        min_poll_seconds=300,
        progress_poll_seconds=300,
        min_progress_poll_seconds=60,
        drops_api_key="secret",
    )
    monkeypatch.setattr("app.api.v1.status.get_settings", lambda: settings)

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        result = await status(session, user)

    assert result.poll_seconds == 900
    assert result.min_poll_seconds == 300
    assert result.progress_poll_seconds == 300
    assert result.min_progress_poll_seconds == 60
    assert result.drops_api_keyed is True
    assert result.twitch_user_connected is False
    assert result.user is not None
    assert result.user.id == user.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_status_reports_unkeyed_when_api_key_missing(monkeypatch):
    engine, factory = await _session()
    settings = Settings(_env_file=None, drops_api_key="")
    monkeypatch.setattr("app.api.v1.status.get_settings", lambda: settings)

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        result = await status(session, user)

    assert result.drops_api_keyed is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_returns_reconnect_fields(monkeypatch):
    engine, factory = await _session()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    provider = FakeTwitchUserProvider()

    async with factory() as session:
        user = await create_user(
            session, twitch_user_id="123", login="viewer"
        )
        account = await connect_account(
            session,
            user,
            access_token="token",
            expires_at=expires_at,
            reconnect_required=True,
            last_error="Twitch login expired",
        )
        account.last_synced_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await session.commit()

        result = await twitch_status(session, user, provider)

        assert result.connected is True
        assert result.login == "viewer"
        assert result.user_id == "123"
        assert result.expires_at == expires_at
        assert result.reconnect_required is True
        assert result.last_error == "Twitch login expired"
        assert result.last_synced_at is not None
        assert provider.calls == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_schedules_profile_only_for_empty_profile(monkeypatch):
    engine, factory = await _session()
    scheduled: list[tuple[int, object]] = []
    monkeypatch.setattr(
        "app.api.v1.progress.get_profile_service",
        lambda: type(
            "Service",
            (),
            {"schedule": lambda _self, user_id, provider=None: scheduled.append((user_id, provider))},
        )(),
    )
    provider = FakeTwitchUserProvider()

    async with factory() as session:
        user = await create_user(
            session, twitch_user_id="123", login="viewer", display_name=""
        )
        await connect_account(session, user, expires_at=future())
        await session.commit()

        result = await twitch_status(session, user, provider)

        assert result.display_name == "viewer"
        assert scheduled == [(user.id, provider)]

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_uses_persisted_profile_without_network_call():
    engine, factory = await _session()
    connected_at = datetime.now(timezone.utc) - timedelta(days=2)
    provider = FakeTwitchUserProvider(
        error=AssertionError("status must not fetch a persisted profile")
    )

    async with factory() as session:
        user = await create_user(
            session,
            twitch_user_id="123",
            login="viewer",
            display_name="Saved Name",
        )
        user.profile_image_url = "https://example.test/saved.png"
        account = await connect_account(session, user, expires_at=None)
        account.connected_at = connected_at
        await session.commit()

        result = await twitch_status(session, user, provider)

        assert result.connected is True
        assert result.display_name == "Saved Name"
        assert result.profile_image_url == "https://example.test/saved.png"
        assert result.connected_at.replace(tzinfo=timezone.utc) == connected_at
        assert provider.calls == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_profile_service_refresh_stores_profile_on_the_user():
    engine, factory = await _session()
    provider = FakeTwitchUserProvider(
        profile={
            "displayName": "Viewer Name",
            "profileImageURL": "https://example.test/avatar.png",
        }
    )

    async with factory() as session:
        user = await create_user(session, twitch_user_id="123", login="viewer")
        await connect_account(session, user, expires_at=None)
        await session.commit()
        user_id = user.id

    await ProfileService().refresh(user_id, provider, session_factory=factory)

    async with factory() as session:
        from app.domain.models import User

        stored = await session.get(User, user_id)
        assert stored is not None
        assert stored.display_name == "Viewer Name"
        assert stored.profile_image_url == "https://example.test/avatar.png"

    assert provider.calls == [("token", "123")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_profile_service_refresh_marks_failure_without_retrying_forever():
    engine, factory = await _session()
    provider = FakeTwitchUserProvider(error=ProviderError("rate limited"))

    async with factory() as session:
        user = await create_user(
            session, twitch_user_id="123", login="viewer", display_name=""
        )
        await connect_account(session, user, expires_at=None)
        await session.commit()
        user_id = user.id

    await ProfileService().refresh(user_id, provider, session_factory=factory)

    async with factory() as session:
        from app.domain.models import User

        stored = await session.get(User, user_id)
        assert stored is not None
        assert stored.display_name == "viewer"
        assert stored.profile_image_url == ""

    await engine.dispose()


@pytest.mark.asyncio
async def test_profile_warm_up_schedules_each_user_with_a_missing_profile(monkeypatch):
    engine, factory = await _session()
    service = ProfileService()
    scheduled: list[int] = []
    monkeypatch.setattr(
        service, "schedule", lambda user_id, provider=None: scheduled.append(user_id)
    )

    async with factory() as session:
        empty = await create_user(
            session, twitch_user_id="1", login="empty", display_name=""
        )
        filled = await create_user(
            session, twitch_user_id="2", login="filled", display_name="Filled"
        )
        disconnected = await create_user(
            session, twitch_user_id="3", login="disconnected", display_name=""
        )
        await connect_account(session, empty, expires_at=None)
        await connect_account(session, filled, expires_at=None)
        await session.commit()
        # disconnected has no Twitch account.
        assert disconnected.id not in (empty.id, filled.id)

    await service.warm_up(session_factory=factory)

    assert scheduled == [empty.id]

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_without_auth_does_not_call_provider():
    engine, factory = await _session()
    provider = FakeTwitchUserProvider()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        result = await twitch_status(session, user, provider)

    assert result.connected is False
    assert result.display_name is None
    assert result.profile_image_url is None
    assert result.connected_at is None
    assert provider.calls == []

    await engine.dispose()
