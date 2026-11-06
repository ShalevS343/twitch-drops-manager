from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.progress import twitch_status
from app.api.v1.status import status
from app.core.config import Settings
from app.core.db import Base
from app.core.exceptions import ProviderError
from app.repositories.twitch_auth import TwitchAuthRepository


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


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
        result = await status(session)

    assert result.poll_seconds == 900
    assert result.min_poll_seconds == 300
    assert result.progress_poll_seconds == 300
    assert result.min_progress_poll_seconds == 60
    assert result.drops_api_keyed is True
    assert result.twitch_user_connected is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_status_reports_unkeyed_when_api_key_missing(monkeypatch):
    engine, factory = await _session()
    settings = Settings(_env_file=None, drops_api_key="")
    monkeypatch.setattr("app.api.v1.status.get_settings", lambda: settings)

    async with factory() as session:
        result = await status(session)

    assert result.drops_api_keyed is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_uses_profile_and_connected_at():
    engine, factory = await _session()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    provider = FakeTwitchUserProvider(
        profile={
            "displayName": "Viewer Name",
            "profileImageURL": "https://example.test/avatar.png",
        }
    )

    async with factory() as session:
        auth = await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=expires_at,
        )
        await session.commit()

        result = await twitch_status(session, provider)

        assert result.connected is True
        assert result.login == "viewer"
        assert result.user_id == "123"
        assert result.expires_at == expires_at
        assert result.display_name == "Viewer Name"
        assert result.profile_image_url == "https://example.test/avatar.png"
        assert result.connected_at == auth.updated_at
        assert provider.calls == [("token", "123")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_falls_back_when_profile_fails():
    engine, factory = await _session()
    provider = FakeTwitchUserProvider(error=ProviderError("rate limited"))

    async with factory() as session:
        await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=None,
        )
        await session.commit()

        result = await twitch_status(session, provider)

        assert result.connected is True
        assert result.login == "viewer"
        assert result.display_name == "viewer"
        assert result.profile_image_url is None
        assert result.connected_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_without_auth_does_not_call_provider():
    engine, factory = await _session()
    provider = FakeTwitchUserProvider()

    async with factory() as session:
        result = await twitch_status(session, provider)

    assert result.connected is False
    assert result.display_name is None
    assert result.profile_image_url is None
    assert result.connected_at is None
    assert provider.calls == []

    await engine.dispose()
