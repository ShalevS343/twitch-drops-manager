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
from app.core.security import create_auth_session
from app.domain.models import User, UserSession, UserWatchFocus
from app.repositories.users import UserRepository
from app.services.factory import get_twitch_user_provider


class FakeTwitchProvider:
    def __init__(self) -> None:
        self.info = {
            "client_id": "client",
            "user_id": "123",
            "login": "viewer",
            "expires_in": 3600,
        }

    def parse_oauth_token(self, _value):
        return "token"

    async def validate(self, _token):
        return dict(self.info)

    async def fetch_profile(self, _access_token, _user_id=""):
        return {}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        registration_code="",
        registration_open=True,
        default_games="",
        twitch_gql_client_id="client",
        cors_origins="",
    )


async def _stack(monkeypatch):
    settings = _settings()
    provider = FakeTwitchProvider()
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

    return engine, factory, app, settings, provider


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def _csrf(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("tdm_csrf") or ""}


async def _login(client: AsyncClient, factory, user_id: int) -> None:
    async with factory() as session:
        raw, csrf, _ = await create_auth_session(session, user_id, 30)
        await session.commit()
    client.cookies.set("tdm_session", raw)
    client.cookies.set("tdm_csrf", csrf)


async def _two_users(factory):
    async with factory() as session:
        repo = UserRepository(session)
        admin = await repo.create(
            twitch_user_id="123", login="admin", role="admin"
        )
        user = await repo.create(twitch_user_id="456", login="user")
        await session.commit()
        return admin.id, user.id


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit.reset_auth_limiter()
    yield
    rate_limit.reset_auth_limiter()


@pytest.mark.asyncio
async def test_admin_routes_require_authentication(monkeypatch):
    engine, _factory, app, _settings, _provider = await _stack(monkeypatch)

    async with _client(app) as client:
        assert (await client.get("/api/v1/admin/users")).status_code == 401

    await engine.dispose()


@pytest.mark.asyncio
async def test_non_admin_gets_403(monkeypatch):
    engine, factory, app, _settings, _provider = await _stack(monkeypatch)
    _admin_id, user_id = await _two_users(factory)

    async with _client(app) as client:
        await _login(client, factory, user_id)
        response = await client.get("/api/v1/admin/users")
        assert response.status_code == 403

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_lists_safe_user_fields_without_secrets(monkeypatch):
    engine, factory, app, _settings, _provider = await _stack(monkeypatch)
    admin_id, user_id = await _two_users(factory)

    async with factory() as session:
        user = await session.get(User, user_id)
        user.telegram_chat_id = "555"
        user.telegram_enabled = True
        await session.commit()

    async with _client(app) as client:
        await _login(client, factory, admin_id)
        response = await client.get("/api/v1/admin/users")
        assert response.status_code == 200
        payload = response.json()
        assert {row["id"] for row in payload} == {admin_id, user_id}
        for row in payload:
            assert set(row) == {
                "id",
                "login",
                "display_name",
                "role",
                "is_active",
                "created_at",
                "last_login_at",
                "telegram_enabled",
            }
        assert "555" not in response.text
        assert "access_token" not in response.text
        assert "telegram_chat_id" not in response.text

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_cannot_disable_themselves(monkeypatch):
    engine, factory, app, _settings, _provider = await _stack(monkeypatch)
    admin_id, _user_id = await _two_users(factory)

    async with _client(app) as client:
        await _login(client, factory, admin_id)
        response = await client.patch(
            f"/api/v1/admin/users/{admin_id}",
            json={"is_active": False},
            headers=_csrf(client),
        )
        assert response.status_code == 400

    await engine.dispose()


@pytest.mark.asyncio
async def test_disabling_a_user_revokes_sessions_and_stops_focus(monkeypatch):
    engine, factory, app, _settings, _provider = await _stack(monkeypatch)
    admin_id, user_id = await _two_users(factory)

    async with factory() as session:
        session.add(UserWatchFocus(user_id=user_id, enabled=True, status="focused"))
        await session.commit()

    async with _client(app) as client:
        await _login(client, factory, admin_id)
        response = await client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={"is_active": False},
            headers=_csrf(client),
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.is_active is False
        sessions = (
            await session.execute(
                select(UserSession).where(UserSession.user_id == user_id)
            )
        ).scalars().all()
        assert sessions == []
        focus = (
            await session.execute(
                select(UserWatchFocus).where(UserWatchFocus.user_id == user_id)
            )
        ).scalar_one()
        assert focus.enabled is False
        assert focus.status == "idle"

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_can_reenable_a_user(monkeypatch):
    engine, factory, app, _settings, _provider = await _stack(monkeypatch)
    admin_id, user_id = await _two_users(factory)

    async with factory() as session:
        user = await session.get(User, user_id)
        user.is_active = False
        await session.commit()

    async with _client(app) as client:
        await _login(client, factory, admin_id)
        response = await client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={"is_active": True},
            headers=_csrf(client),
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_admin_target_returns_404(monkeypatch):
    engine, factory, app, _settings, _provider = await _stack(monkeypatch)
    admin_id, _user_id = await _two_users(factory)

    async with _client(app) as client:
        await _login(client, factory, admin_id)
        response = await client.patch(
            "/api/v1/admin/users/9999",
            json={"is_active": False},
            headers=_csrf(client),
        )
        assert response.status_code == 404

    await engine.dispose()
