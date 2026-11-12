"""Telegram link codes, linking rules, and the session API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.v1.router import api_router
from app.core.db import get_session
from app.core.exceptions import AccountConflictError
from app.core.middleware import CSRFMiddleware
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import create_auth_session
from app.domain.models import TelegramLinkCode, User, UserCampaignStart
from app.repositories.telegram_links import TelegramLinkRepository
from app.services.auth_service import AuthService
from app.services.factory import get_telegram_provider
from app.services.telegram_link_service import TelegramLinkService
from tests.support import create_user, make_engine

BOT_USERNAME = "raspberrypitwitchbot"


class FakeTelegram:
    configured = True

    def __init__(self, *, username: str = BOT_USERNAME, configured: bool = True):
        self.username = username
        self.configured = configured
        self.me_calls = 0

    async def get_me(self) -> dict:
        self.me_calls += 1
        return {"username": self.username}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _code_from(deep_link: str) -> str:
    return deep_link.rsplit("start=", 1)[1]


async def _link_target(session, user):
    provider = FakeTelegram()
    service = TelegramLinkService(session, provider=provider)
    out = await service.create_link(user.id)
    return service, out, _code_from(out.deep_link)


@pytest.mark.asyncio
async def test_create_link_returns_deep_link_and_stores_only_a_hash():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        service, out, code = await _link_target(session, user)

        assert out.deep_link == f"https://t.me/{BOT_USERNAME}?start={code}"
        assert out.bot_username == BOT_USERNAME
        assert out.expires_at.tzinfo is not None
        assert out.expires_at.utcoffset() == timedelta(0)
        assert len(code) >= 32
        rows = (await session.execute(select(TelegramLinkCode))).scalars().all()
        assert len(rows) == 1
        assert rows[0].user_id == user.id
        assert rows[0].code_hash != code
        assert code not in rows[0].code_hash
        ttl = _aware(rows[0].expires_at) - datetime.now(timezone.utc)
        assert timedelta(minutes=9) < ttl <= timedelta(minutes=10)
        assert service.provider.me_calls == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_a_new_link_invalidates_the_previous_unused_code():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        service, _first, first_code = await _link_target(session, user)
        _second_service, _second, _second_code = await _link_target(
            session, user
        )

        rows = (await session.execute(select(TelegramLinkCode))).scalars().all()
        assert len(rows) == 1

        result = await service.link_chat(first_code, "42")
        assert result.ok is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_code_cannot_link():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        service, _out, code = await _link_target(session, user)
        row = (await session.execute(select(TelegramLinkCode))).scalar_one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

        result = await service.link_chat(code, "42")
        assert result.ok is False
        assert result.user is None
        refreshed = await session.get(User, user.id)
        assert refreshed.telegram_chat_id == ""
        assert refreshed.telegram_enabled is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_code_is_one_time_and_links_the_chat():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(
            session, twitch_user_id="1", login="one", display_name="One"
        )
        await session.commit()
        service, _out, code = await _link_target(session, user)

        result = await service.link_chat(code, "42")
        assert result.ok is True
        assert result.user is not None
        assert result.message == (
            "Connected to Twitch Drops Manager as One. "
            "Alerts are on. Send /stop to stop alerts."
        )

        refreshed = await session.get(User, user.id)
        assert refreshed.telegram_chat_id == "42"
        assert refreshed.telegram_enabled is True
        row = (await session.execute(select(TelegramLinkCode))).scalar_one()
        assert row.used_at is not None

        again = await service.link_chat(code, "43")
        assert again.ok is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_only_private_chats_can_link():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        service, _out, code = await _link_target(session, user)

        result = await service.link_chat(code, "42", chat_type="group")
        assert result.ok is False
        assert "private" in result.message.lower()
        refreshed = await session.get(User, user.id)
        assert refreshed.telegram_chat_id == ""
        row = (await session.execute(select(TelegramLinkCode))).scalar_one()
        assert row.used_at is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_another_users_chat_id_cannot_be_claimed():
    engine, factory = await make_engine()
    async with factory() as session:
        owner = await create_user(
            session,
            twitch_user_id="1",
            login="owner",
            telegram_chat_id=" 555 ",
            telegram_enabled=True,
        )
        second = await create_user(session, twitch_user_id="2", login="second")
        await session.commit()
        service, _out, code = await _link_target(session, second)

        result = await service.link_chat(code, "555")
        assert result.ok is False
        assert "another" in result.message.lower()

        refreshed = await session.get(User, second.id)
        assert refreshed.telegram_chat_id == ""
        owner_row = await session.get(User, owner.id)
        assert owner_row.telegram_chat_id.strip() == "555"

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_code_is_rejected():
    engine, factory = await make_engine()
    async with factory() as session:
        await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        service = TelegramLinkService(session, provider=FakeTelegram())

        result = await service.link_chat("not-a-real-code", "42")
        assert result.ok is False
        assert "invalid" in result.message.lower()
        assert "settings" in result.message.lower()

    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_chat_id_owned_by_another_user_is_rejected():
    engine, factory = await make_engine()
    async with factory() as session:
        await create_user(
            session,
            twitch_user_id="1",
            login="owner",
            telegram_chat_id=" 555 ",
            telegram_enabled=True,
        )
        second = await create_user(session, twitch_user_id="2", login="second")
        await session.commit()
        service = AuthService(session)

        with pytest.raises(AccountConflictError):
            await service.update_telegram(second.id, " 555 ", True)

        refreshed = await session.get(User, second.id)
        assert refreshed.telegram_chat_id == ""
        assert refreshed.telegram_enabled is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_unlink_clears_chat_disables_alerts_and_removes_pending_rows():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(
            session,
            twitch_user_id="1",
            login="one",
            telegram_chat_id="42",
            telegram_enabled=True,
        )
        await session.commit()
        service, _out, _code = await _link_target(session, user)
        session.add(UserCampaignStart(user_id=user.id, external_id="campaign-1"))
        await session.commit()

        unlinked = await service.unlink(user.id)

        assert unlinked.telegram_chat_id == ""
        assert unlinked.telegram_enabled is False
        starts = (
            await session.execute(
                select(UserCampaignStart).where(
                    UserCampaignStart.user_id == user.id
                )
            )
        ).scalars().all()
        assert starts == []
        codes = (await session.execute(select(TelegramLinkCode))).scalars().all()
        assert codes == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_codes_are_pruned_and_user_codes_can_be_deleted():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        repo = TelegramLinkRepository(session)
        await repo.create(
            user.id,
            "a" * 64,
            datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        await repo.create(
            user.id,
            "b" * 64,
            datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        await session.commit()

        await repo.delete_expired()
        rows = (await session.execute(select(TelegramLinkCode))).scalars().all()
        assert [row.code_hash for row in rows] == ["b" * 64]

        await repo.delete_for_user(user.id)
        rows = (await session.execute(select(TelegramLinkCode))).scalars().all()
        assert rows == []

    await engine.dispose()


class FakeApiProvider:
    def __init__(self, *, configured: bool = True):
        self.configured = configured

    async def get_me(self) -> dict:
        return {"username": BOT_USERNAME}


async def _api_stack(provider: FakeApiProvider):
    engine, factory = await make_engine()

    async def override_session():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.add_middleware(CSRFMiddleware)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_telegram_provider] = lambda: provider
    return engine, factory, app


async def _login(factory) -> tuple[int, str, str]:
    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        token, csrf, _row = await create_auth_session(session, user.id, 30)
        await session.commit()
        return user.id, token, csrf


@pytest.mark.asyncio
async def test_link_endpoint_requires_a_session():
    engine, _factory, app = await _api_stack(FakeApiProvider())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/v1/telegram/link")

    assert response.status_code == 401
    await engine.dispose()


@pytest.mark.asyncio
async def test_link_endpoint_returns_a_deep_link_for_the_current_user():
    provider = FakeApiProvider()
    engine, factory, app = await _api_stack(provider)
    user_id, token, csrf = await _login(factory)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        client.cookies.set("tdm_session", token)
        client.cookies.set("tdm_csrf", csrf)
        response = await client.post(
            "/api/v1/telegram/link", headers={"X-CSRF-Token": csrf}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deep_link"].startswith(
        f"https://t.me/{BOT_USERNAME}?start="
    )
    assert payload["bot_username"] == BOT_USERNAME
    assert "expires_at" in payload

    async with factory() as session:
        row = (await session.execute(select(TelegramLinkCode))).scalar_one()
        assert row.user_id == user_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_link_endpoint_returns_429_when_rate_limited(monkeypatch):
    provider = FakeApiProvider()
    engine, factory, app = await _api_stack(provider)
    _user_id, token, csrf = await _login(factory)
    limiter = SlidingWindowRateLimiter(1)
    monkeypatch.setattr(
        "app.api.v1.telegram.get_auth_limiter", lambda: limiter
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        client.cookies.set("tdm_session", token)
        client.cookies.set("tdm_csrf", csrf)
        first = await client.post(
            "/api/v1/telegram/link", headers={"X-CSRF-Token": csrf}
        )
        second = await client.post(
            "/api/v1/telegram/link", headers={"X-CSRF-Token": csrf}
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert "retry-after" in second.headers
    await engine.dispose()


@pytest.mark.asyncio
async def test_update_me_rejects_a_chat_owned_by_another_user():
    engine, factory, app = await _api_stack(FakeApiProvider())
    user_id, token, csrf = await _login(factory)

    async with factory() as session:
        await create_user(
            session,
            twitch_user_id="2",
            login="owner",
            telegram_chat_id="555",
            telegram_enabled=True,
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        client.cookies.set("tdm_session", token)
        client.cookies.set("tdm_csrf", csrf)
        response = await client.patch(
            "/api/v1/auth/me",
            json={"telegram_chat_id": " 555 ", "telegram_enabled": True},
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 409
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id == ""
        assert user.telegram_enabled is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_link_endpoint_returns_400_without_a_bot_token():
    engine, factory, app = await _api_stack(FakeApiProvider(configured=False))
    _user_id, token, csrf = await _login(factory)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        client.cookies.set("tdm_session", token)
        client.cookies.set("tdm_csrf", csrf)
        response = await client.post(
            "/api/v1/telegram/link", headers={"X-CSRF-Token": csrf}
        )

    assert response.status_code == 400
    await engine.dispose()


@pytest.mark.asyncio
async def test_unlink_endpoint_clears_the_current_users_chat():
    engine, factory, app = await _api_stack(FakeApiProvider())
    user_id, token, csrf = await _login(factory)

    async with factory() as session:
        user = await session.get(User, user_id)
        user.telegram_chat_id = "42"
        user.telegram_enabled = True
        session.add(UserCampaignStart(user_id=user_id, external_id="campaign-1"))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        client.cookies.set("tdm_session", token)
        client.cookies.set("tdm_csrf", csrf)
        response = await client.post(
            "/api/v1/telegram/unlink", headers={"X-CSRF-Token": csrf}
        )

    assert response.status_code == 200
    assert response.json() == {"unlinked": True}

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id == ""
        assert user.telegram_enabled is False
        starts = (
            await session.execute(
                select(UserCampaignStart).where(
                    UserCampaignStart.user_id == user_id
                )
            )
        ).scalars().all()
        assert starts == []

    await engine.dispose()
