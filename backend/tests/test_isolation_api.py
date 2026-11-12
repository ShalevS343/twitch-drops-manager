"""API-level isolation between two signed-in users."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.router import api_router
from app.core.config import Settings
from app.core.db import Base, get_session
from app.core.middleware import CSRFMiddleware
from app.core.security import create_auth_session
from app.domain.models import (
    Campaign,
    Game,
    Stream,
    StreamCampaignMatch,
    UserCampaignCompletion,
    UserDropProgress,
    UserGame,
    UserWatchFocus,
)
from app.repositories.users import UserRepository


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        cors_origins="",
        registration_code="",
        telegram_bot_token="",
    )


async def _stack(monkeypatch):
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

    monkeypatch.setattr("app.api.v1.status.get_settings", lambda: settings)
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: settings)

    return engine, factory, app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _login(client: AsyncClient, factory, user_id: int) -> None:
    async with factory() as session:
        raw, csrf, _ = await create_auth_session(session, user_id, 30)
        await session.commit()
    client.cookies.set("tdm_session", raw)
    client.cookies.set("tdm_csrf", csrf)


def _csrf(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("tdm_csrf") or ""}


async def _seed(factory):
    async with factory() as session:
        users = UserRepository(session)
        first = await users.create(twitch_user_id="1", login="first")
        second = await users.create(twitch_user_id="2", login="second")
        admin = await users.create(
            twitch_user_id="3", login="admin", role="admin"
        )

        rust = Game(name="Rust", box_art_url="https://example.test/rust.jpg")
        minecraft = Game(name="Minecraft")
        session.add_all([rust, minecraft])
        await session.flush()

        session.add_all(
            [
                UserGame(user_id=first.id, game_id=rust.id),
                UserGame(user_id=second.id, game_id=minecraft.id),
            ]
        )

        rust_campaign = Campaign(
            external_id="Rust:rust-1",
            game_id=rust.id,
            name="Rust Drops",
            status="ACTIVE",
            ends_at="2099-12-01T00:00:00Z",
        )
        mc_campaign = Campaign(
            external_id="Minecraft:mc-1",
            game_id=minecraft.id,
            name="Minecraft Drops",
            status="ACTIVE",
            ends_at="2099-12-01T00:00:00Z",
        )
        session.add_all([rust_campaign, mc_campaign])
        await session.flush()

        for login, game, campaign in (
            ("rust-stream", rust, rust_campaign),
            ("mc-stream", minecraft, mc_campaign),
        ):
            stream = Stream(
                user_login=login,
                user_name=login.title(),
                game_id=game.id,
                title=login,
                viewers=10,
                language="en",
                url=f"https://www.twitch.tv/{login}",
                live=True,
            )
            session.add(stream)
            await session.flush()
            session.add(
                StreamCampaignMatch(
                    stream_id=stream.id,
                    campaign_id=campaign.id,
                    eligibility="Potential campaign match; verify on Twitch",
                )
            )

        session.add_all(
            [
                UserDropProgress(
                    user_id=first.id,
                    drop_id="first-drop",
                    drop_name="First Drop",
                    campaign_gql_id="rust-1",
                    campaign_name="Rust Drops",
                    campaign_ends_at="2099-12-01T00:00:00Z",
                    game_name="Rust",
                    required_minutes=60,
                    current_minutes=10,
                ),
                UserDropProgress(
                    user_id=second.id,
                    drop_id="second-drop",
                    drop_name="Second Drop",
                    campaign_gql_id="mc-1",
                    campaign_name="Minecraft Drops",
                    campaign_ends_at="2099-12-01T00:00:00Z",
                    game_name="Minecraft",
                    required_minutes=60,
                    current_minutes=20,
                ),
                UserCampaignCompletion(
                    user_id=second.id,
                    campaign_gql_id="mc-1",
                    campaign_name="Minecraft Drops",
                    game_name="Minecraft",
                ),
                UserWatchFocus(
                    user_id=first.id, enabled=True, status="focused"
                ),
            ]
        )
        await session.commit()
        return first.id, second.id, admin.id


@pytest.mark.asyncio
async def test_games_show_the_callers_own_selection(monkeypatch):
    engine, factory, app = await _stack(monkeypatch)
    first_id, second_id, _admin_id = await _seed(factory)

    async with _client(app) as client:
        await _login(client, factory, first_id)
        payload = (await client.get("/api/v1/games")).json()
        assert {row["name"]: row["selected"] for row in payload} == {
            "Rust": True,
            "Minecraft": False,
        }

        # Replacing one user's selection does not touch the other user's rows.
        response = await client.put(
            "/api/v1/games",
            json={"games": ["Minecraft"]},
            headers=_csrf(client),
        )
        assert response.status_code == 200
        assert response.json()["games"] == ["Minecraft"]

    async with _client(app) as client:
        await _login(client, factory, second_id)
        payload = (await client.get("/api/v1/games")).json()
        assert {row["name"]: row["selected"] for row in payload} == {
            "Rust": False,
            "Minecraft": True,
        }

    await engine.dispose()


@pytest.mark.asyncio
async def test_campaigns_and_streams_are_filtered_per_user(monkeypatch):
    engine, factory, app = await _stack(monkeypatch)
    first_id, second_id, _admin_id = await _seed(factory)

    async with _client(app) as client:
        await _login(client, factory, first_id)
        campaigns = (await client.get("/api/v1/campaigns")).json()
        streams = (await client.get("/api/v1/streams")).json()
        assert [row["name"] for row in campaigns] == ["Rust Drops"]
        assert [row["user_login"] for row in streams] == ["rust-stream"]
        # The Minecraft campaign is uncompleted for this caller, but the game
        # is not selected, so its live stream must stay hidden.
        assert "mc-stream" not in {row["user_login"] for row in streams}

    async with _client(app) as client:
        await _login(client, factory, second_id)
        campaigns = (await client.get("/api/v1/campaigns")).json()
        streams = (await client.get("/api/v1/streams")).json()
        assert [row["name"] for row in campaigns] == ["Minecraft Drops"]
        assert campaigns[0]["completed"] is True
        assert [row["user_login"] for row in streams] == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_status_progress_and_watch_queue_are_per_user(monkeypatch):
    engine, factory, app = await _stack(monkeypatch)
    first_id, second_id, _admin_id = await _seed(factory)

    async with _client(app) as client:
        await _login(client, factory, first_id)
        status = (await client.get("/api/v1/status")).json()
        progress = (await client.get("/api/v1/progress")).json()
        queue = (await client.get("/api/v1/watch-queue")).json()

        assert status["user"]["id"] == first_id
        assert status["games_selected"] == ["Rust"]
        assert [row["campaign_id"] for row in progress] == ["rust-1"]
        assert [item["user_login"] for item in queue] == ["rust-stream"]

    async with _client(app) as client:
        await _login(client, factory, second_id)
        status = (await client.get("/api/v1/status")).json()
        progress = (await client.get("/api/v1/progress")).json()
        queue = (await client.get("/api/v1/watch-queue")).json()

        assert status["user"]["id"] == second_id
        assert status["games_selected"] == ["Minecraft"]
        assert [row["campaign_id"] for row in progress] == ["mc-1"]
        assert [item["user_login"] for item in queue] == ["mc-stream"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_watcher_state_is_per_user(monkeypatch):
    engine, factory, app = await _stack(monkeypatch)
    first_id, second_id, _admin_id = await _seed(factory)

    async with _client(app) as first, _client(app) as second:
        await _login(first, factory, first_id)
        await _login(second, factory, second_id)

        first_state = (await first.get("/api/v1/watcher")).json()
        second_state = (await second.get("/api/v1/watcher")).json()

        assert first_state["enabled"] is True
        assert second_state["enabled"] is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_personal_endpoints_require_a_session(monkeypatch):
    engine, _factory, app = await _stack(monkeypatch)

    async with _client(app) as client:
        for path in (
            "/api/v1/games",
            "/api/v1/campaigns",
            "/api/v1/streams",
            "/api/v1/status",
            "/api/v1/progress",
            "/api/v1/watch-queue",
            "/api/v1/watcher",
        ):
            assert (await client.get(path)).status_code == 401, path

    await engine.dispose()


@pytest.mark.asyncio
async def test_non_admin_cannot_trigger_a_scan(monkeypatch):
    engine, factory, app = await _stack(monkeypatch)
    _first_id, second_id, _admin_id = await _seed(factory)

    async with _client(app) as client:
        await _login(client, factory, second_id)
        response = await client.post("/api/v1/scans", headers=_csrf(client))
        assert response.status_code == 403

    await engine.dispose()
