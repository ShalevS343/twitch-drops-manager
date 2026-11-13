"""Device-code login API: start, poll, cookies, terminal states, cancel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.router import api_router
from app.core import rate_limit
from app.core.config import Settings
from app.core.db import Base, get_session
from app.core.middleware import CSRFMiddleware
from app.core.rate_limit import SlidingWindowRateLimiter
from app.domain.models import TwitchAccount, TwitchDeviceFlow
from app.services.factory import get_twitch_user_provider
from tests.support import create_user

SMART_TV = "smart-tv-client"


class FakeDeviceProvider:
    def __init__(self) -> None:
        self.start_response = {
            "device_code": "device-secret",
            "user_code": "ABCD1234",
            "verification_uri": "https://www.twitch.tv/activate",
            "expires_in": 1800,
            "interval": 5,
        }
        self.poll_results = []
        self.info = {
            "client_id": SMART_TV,
            "user_id": "123",
            "login": "viewer",
            "expires_in": 3600,
        }

    async def start_device_flow(self):
        return dict(self.start_response)

    async def poll_device_token(self, device_code, client_id):
        result = self.poll_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def validate(self, _token):
        return dict(self.info)

    async def fetch_profile(self, access_token, user_id="", client_id=""):
        return {"displayName": "Viewer Name"}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        registration_open=True,
        registration_code="",
        owner_twitch_id="",
        default_games="",
        twitch_device_grant_client_id=SMART_TV,
        twitch_device_client_id="android-client",
        cors_origins="",
        telegram_bot_token="",
    )


async def _stack(monkeypatch, provider):
    settings = _settings()
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.add_middleware(CSRFMiddleware)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_twitch_user_provider] = lambda: provider

    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.twitch_device_service.get_settings", lambda: settings
    )
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.auth.get_settings", lambda: settings)

    async def noop_sync(_user_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.v1.auth._first_progress_sync", noop_sync)
    rate_limit.reset_auth_limiter()
    return engine, factory, app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_start_returns_code_and_never_exposes_device_code(monkeypatch):
    provider = FakeDeviceProvider()
    engine, _factory, app = await _stack(monkeypatch, provider)

    async with _client(app) as client:
        response = await client.post("/api/v1/auth/twitch/device/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["flow_id"]
    assert payload["user_code"] == "ABCD1234"
    assert payload["verification_uri"] == "https://www.twitch.tv/activate"
    assert payload["interval"] == 5
    assert "expires_at" in payload
    assert "device_code" not in payload
    assert "device-secret" not in response.text

    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_poll_returns_interval(monkeypatch):
    from app.core.exceptions import DeviceFlowPendingError

    provider = FakeDeviceProvider()
    provider.poll_results = [DeviceFlowPendingError("pending")]
    engine, _factory, app = await _stack(monkeypatch, provider)

    async with _client(app) as client:
        start = await client.post("/api/v1/auth/twitch/device/start")
        flow_id = start.json()["flow_id"]

        first = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert first.status_code == 200
        assert first.json() == {"status": "pending", "interval": 5}
        assert client.cookies.get("tdm_session") is None

        # The second call is throttled server-side; it stays pending and does
        # not consume the queued (empty) provider response.
        second = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert second.status_code == 200
        assert second.json() == {"status": "pending", "interval": 5}

    await engine.dispose()


@pytest.mark.asyncio
async def test_success_sets_cookies_and_stores_the_smart_tv_client(monkeypatch):
    provider = FakeDeviceProvider()
    provider.poll_results = [
        {"access_token": "access-token", "expires_in": 3600}
    ]
    engine, factory, app = await _stack(monkeypatch, provider)

    async with _client(app) as client:
        start = await client.post("/api/v1/auth/twitch/device/start")
        flow_id = start.json()["flow_id"]

        response = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["connected"] is True
        assert payload["created"] is True
        assert payload["user"]["login"] == "viewer"
        assert client.cookies.get("tdm_session")
        assert client.cookies.get("tdm_csrf")

        me = await client.get("/api/v1/auth/me")
        assert me.json()["authenticated"] is True

        # One-time use.
        again = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert again.status_code == 410

    async with factory() as session:
        account = (
            await session.execute(select(TwitchAccount))
        ).scalar_one()
        assert account.access_token == "access-token"
        assert account.client_id == SMART_TV

    await engine.dispose()


@pytest.mark.asyncio
async def test_denied_flow_returns_400_and_becomes_gone(monkeypatch):
    from app.core.exceptions import DeviceFlowAccessDeniedError

    provider = FakeDeviceProvider()
    provider.poll_results = [DeviceFlowAccessDeniedError("denied")]
    engine, _factory, app = await _stack(monkeypatch, provider)

    async with _client(app) as client:
        start = await client.post("/api/v1/auth/twitch/device/start")
        flow_id = start.json()["flow_id"]

        response = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert response.status_code == 400
        assert client.cookies.get("tdm_session") is None

        again = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert again.status_code == 410

    await engine.dispose()


@pytest.mark.asyncio
async def test_locally_expired_flow_returns_400(monkeypatch):
    provider = FakeDeviceProvider()
    engine, factory, app = await _stack(monkeypatch, provider)

    async with _client(app) as client:
        start = await client.post("/api/v1/auth/twitch/device/start")
        flow_id = start.json()["flow_id"]

        async with factory() as session:
            flow = (
                await session.execute(select(TwitchDeviceFlow))
            ).scalar_one()
            flow.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        response = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert response.status_code == 400

    await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_deletes_the_flow(monkeypatch):
    provider = FakeDeviceProvider()
    engine, _factory, app = await _stack(monkeypatch, provider)

    async with _client(app) as client:
        start = await client.post("/api/v1/auth/twitch/device/start")
        flow_id = start.json()["flow_id"]

        response = await client.delete(f"/api/v1/auth/twitch/device/{flow_id}")
        assert response.status_code == 200
        assert response.json() == {"cancelled": True}

        poll = await client.get(f"/api/v1/auth/twitch/device/{flow_id}")
        assert poll.status_code == 410

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_flow_is_410(monkeypatch):
    provider = FakeDeviceProvider()
    engine, _factory, app = await _stack(monkeypatch, provider)

    async with _client(app) as client:
        response = await client.get("/api/v1/auth/twitch/device/unknown")
        assert response.status_code == 410

    await engine.dispose()


@pytest.mark.asyncio
async def test_start_is_rate_limited(monkeypatch):
    provider = FakeDeviceProvider()
    engine, _factory, app = await _stack(monkeypatch, provider)
    limiter = SlidingWindowRateLimiter(1)
    monkeypatch.setattr(
        "app.core.rate_limit.get_auth_limiter",
        lambda: limiter,
    )

    async with _client(app) as client:
        first = await client.post("/api/v1/auth/twitch/device/start")
        assert first.status_code == 200
        second = await client.post("/api/v1/auth/twitch/device/start")
        assert second.status_code == 429
        assert "retry-after" in second.headers

    await engine.dispose()


@pytest.mark.asyncio
async def test_signed_in_start_binds_the_current_user(monkeypatch):
    provider = FakeDeviceProvider()
    engine, factory, app = await _stack(monkeypatch, provider)

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        user_id = user.id

    async with _client(app) as client:
        # The public start endpoint is CSRF-exempt like the implicit connect
        # endpoint, but still sees the current session cookie.
        from app.core.security import create_auth_session

        async with factory() as session:
            token, _csrf, _row = await create_auth_session(session, user_id, 30)
            await session.commit()
        client.cookies.set("tdm_session", token)

        response = await client.post("/api/v1/auth/twitch/device/start")
        assert response.status_code == 200
        flow_id = response.json()["flow_id"]

    async with factory() as session:
        flow = (
            await session.execute(
                select(TwitchDeviceFlow).where(
                    TwitchDeviceFlow.flow_id == flow_id
                )
            )
        ).scalar_one()
        assert flow.current_user_id == user_id

    await engine.dispose()
