from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.progress import twitch_connect, twitch_status
from app.api.v1.status import status
from app.core.config import Settings
from app.core.db import Base
from app.core.exceptions import ProviderError
from app.domain.schemas import TwitchConnectIn
from app.repositories.twitch_auth import TwitchAuthRepository
from app.repositories.twitch_profile import TwitchProfileRepository


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

        # The failure is persisted as an empty profile so later status calls
        # never retry Twitch GQL until the account is reconnected.
        profile = await TwitchProfileRepository(session).get()
        assert profile is not None
        assert profile.display_name == ""
        assert profile.profile_image_url == ""

        second = await twitch_status(session, provider)
        assert second.display_name == "viewer"
        assert provider.calls == [("token", "123")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_status_uses_persisted_profile_without_network_call():
    engine, factory = await _session()
    connected_at = datetime.now(timezone.utc) - timedelta(days=2)
    provider = FakeTwitchUserProvider(
        error=AssertionError("status must not fetch a persisted profile")
    )

    async with factory() as session:
        await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=None,
        )
        await TwitchProfileRepository(session).save(
            user_id="123",
            display_name="Saved Name",
            profile_image_url="https://example.test/saved.png",
            connected_at=connected_at,
        )
        await session.commit()

        result = await twitch_status(session, provider)

        assert result.connected is True
        assert result.login == "viewer"
        assert result.display_name == "Saved Name"
        assert result.profile_image_url == "https://example.test/saved.png"
        assert result.connected_at.replace(tzinfo=timezone.utc) == connected_at
        assert provider.calls == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_profile_repository_save_get_and_clear():
    engine, factory = await _session()

    async with factory() as session:
        repo = TwitchProfileRepository(session)
        assert await repo.get() is None

        connected_at = datetime.now(timezone.utc)
        await repo.save(
            user_id="123",
            display_name="Viewer Name",
            profile_image_url="https://example.test/avatar.png",
            connected_at=connected_at,
        )
        await session.commit()

        profile = await repo.get()
        assert profile is not None
        assert profile.user_id == "123"
        assert profile.display_name == "Viewer Name"
        assert profile.profile_image_url == "https://example.test/avatar.png"
        assert profile.connected_at.replace(tzinfo=timezone.utc) == connected_at

        await repo.clear()
        await session.commit()
        assert await repo.get() is None

    await engine.dispose()


class FakeConnectProvider:
    def __init__(self, profile=None, error=None):
        self.profile = profile or {}
        self.error = error
        self.calls = []
        self.settings = SimpleNamespace(
            gql_client_id="client",
            twitch_oauth_redirect_uri="https://example.test/callback",
        )

    def parse_oauth_token(self, _value):
        return "token"

    async def validate(self, _token):
        return {
            "client_id": "client",
            "user_id": "123",
            "login": "viewer",
            "expires_in": 3600,
        }

    async def fetch_profile(self, access_token, user_id=""):
        self.calls.append((access_token, user_id))
        if self.error is not None:
            raise self.error
        return self.profile


class FakeProgressService:
    async def run(self):
        return SimpleNamespace(drop_count=0)


@pytest.mark.asyncio
async def test_twitch_connect_persists_profile(monkeypatch):
    engine, factory = await _session()
    provider = FakeConnectProvider(
        profile={
            "displayName": "Viewer Name",
            "profileImageURL": "https://example.test/avatar.png",
        }
    )
    monkeypatch.setattr(
        "app.api.v1.progress.build_progress_service",
        lambda _session: FakeProgressService(),
    )

    async with factory() as session:
        result = await twitch_connect(
            TwitchConnectIn(redirect_url="https://example.test/#access_token=token"),
            session,
            provider,
        )

        assert result.connected is True
        assert provider.calls == [("token", "123")]

        profile = await TwitchProfileRepository(session).get()
        assert profile is not None
        assert profile.user_id == "123"
        assert profile.display_name == "Viewer Name"
        assert profile.profile_image_url == "https://example.test/avatar.png"
        assert profile.connected_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_twitch_connect_saves_empty_profile_when_fetch_fails(monkeypatch):
    engine, factory = await _session()
    provider = FakeConnectProvider(error=ProviderError("rate limited"))
    monkeypatch.setattr(
        "app.api.v1.progress.build_progress_service",
        lambda _session: FakeProgressService(),
    )

    async with factory() as session:
        result = await twitch_connect(
            TwitchConnectIn(redirect_url="https://example.test/#access_token=token"),
            session,
            provider,
        )

        assert result.connected is True

        profile = await TwitchProfileRepository(session).get()
        assert profile is not None
        assert profile.user_id == "123"
        assert profile.display_name == ""
        assert profile.profile_image_url == ""
        assert profile.connected_at is not None

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
