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
from app.domain.models import (
    TwitchAccount,
    User,
    UserDropProgress,
    UserSession,
)
from app.repositories.users import UserRepository
from app.services.auth_service import AuthService
from app.services.factory import get_twitch_user_provider


class FakeTwitchProvider:
    authorize_url = "https://id.twitch.tv/oauth2/authorize?client_id=client"
    settings = type(
        "ProviderSettings",
        (),
        {"twitch_oauth_redirect_uri": "https://www.twitch.tv/"},
    )()

    def __init__(self) -> None:
        self.info = {
            "client_id": "client",
            "user_id": "123",
            "login": "viewer",
            "expires_in": 3600,
        }
        self.profile = {
            "displayName": "Viewer Name",
            "profileImageURL": "https://example.test/avatar.png",
        }

    def parse_oauth_token(self, _value):
        return "token"

    async def validate(self, _token):
        return dict(self.info)

    async def fetch_profile(self, _access_token, _user_id=""):
        return dict(self.profile)

    def as_user(self, user_id: str, login: str) -> None:
        self.info = {
            "client_id": "client",
            "user_id": user_id,
            "login": login,
            "expires_in": 3600,
        }


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "registration_code": "",
        "registration_open": False,
        "default_games": "",
        "twitch_gql_client_id": "client",
        "telegram_bot_token": "",
        "cors_origins": "",
    }
    values.update(overrides)
    return Settings(**values)


async def _stack(monkeypatch, settings: Settings, provider: FakeTwitchProvider):
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
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.auth.get_settings", lambda: settings)
    rate_limit.reset_auth_limiter()

    return engine, factory, app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def _csrf(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("tdm_csrf") or ""}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit.reset_auth_limiter()
    yield
    rate_limit.reset_auth_limiter()


@pytest.mark.asyncio
async def test_auth_me_unauthenticated_reports_registration_state(monkeypatch):
    settings = _settings()
    engine, _factory, app = await _stack(monkeypatch, settings, FakeTwitchProvider())

    async with _client(app) as client:
        response = await client.get("/api/v1/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is False
    assert payload["user"] is None
    assert payload["registration"] == {"open": True, "invite_required": False}
    assert payload["telegram_bot_configured"] is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_authorize_endpoint_is_public(monkeypatch):
    settings = _settings()
    provider = FakeTwitchProvider()
    engine, _factory, app = await _stack(monkeypatch, settings, provider)

    async with _client(app) as client:
        response = await client.get("/api/v1/auth/twitch/authorize")

    assert response.status_code == 200
    assert response.json() == {
        "authorize_url": provider.authorize_url,
        "redirect_uri": "https://www.twitch.tv/",
    }

    await engine.dispose()


@pytest.mark.asyncio
async def test_first_connect_sets_cookies_and_me_reflects_the_user(monkeypatch):
    settings = _settings()
    engine, _factory, app = await _stack(monkeypatch, settings, FakeTwitchProvider())

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["connected"] is True
        assert payload["created"] is True
        assert payload["user"]["role"] == "admin"
        assert payload["user"]["login"] == "viewer"

        assert client.cookies.get("tdm_session")
        assert client.cookies.get("tdm_csrf")
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=lax" in response.headers["set-cookie"]

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body["authenticated"] is True
        assert body["user"]["id"] == payload["user"]["id"]
        assert body["registration"] == {"open": False, "invite_required": False}

    await engine.dispose()


@pytest.mark.asyncio
async def test_public_connect_with_bad_code_is_403(monkeypatch):
    settings = _settings(registration_code="secret")
    provider = FakeTwitchProvider()
    engine, factory, app = await _stack(monkeypatch, settings, provider)

    async with factory() as session:
        await AuthService(session, settings=settings, provider=provider).connect(
            "url", ""
        )

    provider.as_user("456", "second")
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/auth/twitch/connect",
            json={
                "redirect_url": "https://twitch.tv/#access_token=token",
                "invite_code": "wrong",
            },
        )
        assert response.status_code == 403
        assert client.cookies.get("tdm_session") is None

        response = await client.post(
            "/api/v1/auth/twitch/connect",
            json={
                "redirect_url": "https://twitch.tv/#access_token=token",
                "invite_code": "secret",
            },
        )
        assert response.status_code == 200
        assert response.json()["created"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_connect_rate_limit_returns_429(monkeypatch):
    settings = _settings()
    provider = FakeTwitchProvider()
    engine, _factory, app = await _stack(monkeypatch, settings, provider)
    limiter = SlidingWindowRateLimiter(1)
    monkeypatch.setattr(
        "app.api.v1.auth.get_auth_limiter",
        lambda: limiter,
    )

    async with _client(app) as client:
        first = await client.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        assert first.status_code == 200

        second = await client.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        assert second.status_code == 429
        assert "retry-after" in second.headers

    await engine.dispose()


@pytest.mark.asyncio
async def test_connect_requires_a_valid_twitch_identity(monkeypatch):
    settings = _settings()
    provider = FakeTwitchProvider()
    provider.info = {"client_id": "client", "login": "viewer"}
    engine, _factory, app = await _stack(monkeypatch, settings, provider)

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        assert response.status_code == 400

    await engine.dispose()


@pytest.mark.asyncio
async def test_logout_clears_cookies_and_deletes_the_session(monkeypatch):
    settings = _settings()
    engine, factory, app = await _stack(
        monkeypatch, settings, FakeTwitchProvider()
    )

    async with _client(app) as client:
        await client.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        response = await client.post("/api/v1/auth/logout", headers=_csrf(client))
        assert response.status_code == 200
        assert client.cookies.get("tdm_session") in (None, "")

        me = await client.get("/api/v1/auth/me")
        assert me.json()["authenticated"] is False

    async with factory() as session:
        assert (await session.execute(select(UserSession))).scalars().all() == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_patch_telegram_only_affects_the_current_user(monkeypatch):
    settings = _settings(registration_open=True)
    provider = FakeTwitchProvider()
    engine, _factory, app = await _stack(monkeypatch, settings, provider)

    async with _client(app) as first, _client(app) as second:
        first_connect = await first.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        first_id = first_connect.json()["user"]["id"]

        provider.as_user("456", "second")
        second_connect = await second.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        assert second_connect.json()["user"]["id"] != first_id

        response = await first.patch(
            "/api/v1/auth/me",
            json={"telegram_chat_id": "555", "telegram_enabled": True},
            headers=_csrf(first),
        )
        assert response.status_code == 200
        assert response.json()["telegram_chat_id"] == "555"
        assert response.json()["telegram_enabled"] is True

        other = await second.get("/api/v1/auth/me")
        assert other.json()["user"]["telegram_chat_id"] == ""
        assert other.json()["user"]["telegram_enabled"] is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_disconnect_clears_that_users_data_only(monkeypatch):
    settings = _settings()
    provider = FakeTwitchProvider()
    engine, factory, app = await _stack(monkeypatch, settings, provider)

    async with _client(app) as client:
        connect = await client.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        user_id = connect.json()["user"]["id"]

    async with factory() as session:
        other = await UserRepository(session).create(
            twitch_user_id="999", login="other"
        )
        session.add_all(
            [
                UserDropProgress(user_id=user_id, drop_id="drop-current"),
                UserDropProgress(user_id=other.id, drop_id="drop-other"),
            ]
        )
        await session.commit()
        other_id = other.id

    async with _client(app) as client:
        client.cookies.set("tdm_session", connect.cookies["tdm_session"])
        client.cookies.set("tdm_csrf", connect.cookies["tdm_csrf"])
        response = await client.post(
            "/api/v1/auth/twitch/disconnect", headers=_csrf(client)
        )
        assert response.status_code == 200

    async with factory() as session:
        rows = (
            await session.execute(select(UserDropProgress))
        ).scalars().all()
        assert {row.user_id for row in rows} == {other_id}
        assert await session.get(User, user_id) is not None
        assert (
            await session.execute(
                select(TwitchAccount).where(TwitchAccount.user_id == user_id)
            )
        ).scalar_one_or_none() is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_session_endpoints_require_authentication(monkeypatch):
    settings = _settings()
    engine, _factory, app = await _stack(
        monkeypatch, settings, FakeTwitchProvider()
    )

    async with _client(app) as client:
        assert (await client.post("/api/v1/auth/logout")).status_code == 401
        assert (
            await client.patch("/api/v1/auth/me", json={"telegram_chat_id": ""})
        ).status_code == 401
        assert (
            await client.post("/api/v1/auth/twitch/disconnect")
        ).status_code == 401

    await engine.dispose()


@pytest.mark.asyncio
async def test_connect_triggers_one_first_sync_after_a_successful_session(monkeypatch):
    settings = _settings()
    provider = FakeTwitchProvider()
    engine, _factory, app = await _stack(monkeypatch, settings, provider)
    synced: list[int] = []

    async def fake_sync(user_id: int) -> None:
        synced.append(user_id)

    monkeypatch.setattr("app.api.v1.auth._first_progress_sync", fake_sync)

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/auth/twitch/connect",
            json={"redirect_url": "https://twitch.tv/#access_token=token"},
        )
        assert response.status_code == 200
        assert synced == [response.json()["user"]["id"]]

    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_registration_does_not_trigger_a_sync(monkeypatch):
    settings = _settings(registration_code="secret")
    provider = FakeTwitchProvider()
    engine, factory, app = await _stack(monkeypatch, settings, provider)
    synced: list[int] = []

    async def fake_sync(user_id: int) -> None:
        synced.append(user_id)

    monkeypatch.setattr("app.api.v1.auth._first_progress_sync", fake_sync)

    async with factory() as session:
        await AuthService(session, settings=settings, provider=provider).connect(
            "url", ""
        )
    synced.clear()
    provider.as_user("456", "second")

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/auth/twitch/connect",
            json={
                "redirect_url": "https://twitch.tv/#access_token=token",
                "invite_code": "wrong",
            },
        )
        assert response.status_code == 403
        assert synced == []

    await engine.dispose()
