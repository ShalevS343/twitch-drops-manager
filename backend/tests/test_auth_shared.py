"""Shared login completion used by implicit and device-code flows."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.exceptions import (
    AccountConflictError,
    AccountDisabledError,
    InvalidAuthRequestError,
    RegistrationClosedError,
)
from app.domain.models import TwitchAccount, UserSession
from app.repositories.users import UserRepository
from app.services.auth_service import AuthService
from tests.support import make_engine

ANDROID = "android-client"
SMART_TV = "smart-tv-client"


class FakeTwitchProvider:
    def __init__(self, info, profile=None):
        self.info = info
        self.profile = profile or {}
        self.profile_calls = []

    def parse_oauth_token(self, _value):
        return "access-token"

    async def validate(self, _token):
        return dict(self.info)

    async def fetch_profile(self, access_token, user_id="", client_id=""):
        self.profile_calls.append((access_token, user_id, client_id))
        return dict(self.profile)


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "registration_code": "",
        "registration_open": False,
        "owner_twitch_id": "123",
        "default_games": "",
        "twitch_device_client_id": ANDROID,
        "twitch_gql_client_id": ANDROID,
    }
    values.update(overrides)
    return Settings(**values)


def _info(**overrides):
    values = {
        "client_id": ANDROID,
        "user_id": "123",
        "login": "viewer",
        "expires_in": 3600,
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_complete_login_creates_user_session_and_stores_client_id():
    engine, factory = await make_engine()
    provider = FakeTwitchProvider(
        _info(), profile={"displayName": "Viewer Name"}
    )

    async with factory() as session:
        service = AuthService(session, settings=_settings(), provider=provider)
        result = await service.complete_login(
            "access-token",
            _info(),
            invite_code="",
            current_user=None,
            client_id=ANDROID,
        )

        assert result.created is True
        assert result.user.role == "admin"
        account = (
            await session.execute(
                select(TwitchAccount).where(
                    TwitchAccount.user_id == result.user.id
                )
            )
        ).scalar_one()
        assert account.access_token == "access-token"
        assert account.client_id == ANDROID
        assert provider.profile_calls == [("access-token", "123", ANDROID)]
        stored_session = (
            await session.execute(
                select(UserSession).where(
                    UserSession.user_id == result.user.id
                )
            )
        ).scalar_one()
        assert stored_session.token_hash != result.session_token

    await engine.dispose()


@pytest.mark.asyncio
async def test_implicit_connect_enforces_and_stores_the_android_client():
    engine, factory = await make_engine()
    provider = FakeTwitchProvider(_info())

    async with factory() as session:
        service = AuthService(session, settings=_settings(), provider=provider)
        result = await service.connect("url")

        account = (
            await session.execute(
                select(TwitchAccount).where(
                    TwitchAccount.user_id == result.user.id
                )
            )
        ).scalar_one()
        assert account.client_id == ANDROID

    await engine.dispose()


@pytest.mark.asyncio
async def test_implicit_connect_rejects_a_token_from_another_client():
    engine, factory = await make_engine()
    provider = FakeTwitchProvider(_info(client_id=SMART_TV))

    async with factory() as session:
        service = AuthService(session, settings=_settings(), provider=provider)
        with pytest.raises(InvalidAuthRequestError):
            await service.connect("url")

    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_login_reconnects_an_existing_user_and_updates_client():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        session.add(
            TwitchAccount(
                user_id=user.id,
                access_token="old-token",
                client_id=ANDROID,
                connected_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

        service = AuthService(
            session,
            settings=_settings(),
            provider=FakeTwitchProvider(_info(client_id=SMART_TV)),
        )
        result = await service.complete_login(
            "new-token",
            _info(client_id=SMART_TV),
            invite_code="",
            current_user=user,
            client_id=SMART_TV,
        )

        assert result.created is False
        assert result.user.id == user.id
        account = (
            await session.execute(
                select(TwitchAccount).where(TwitchAccount.user_id == user.id)
            )
        ).scalar_one()
        assert account.access_token == "new-token"
        assert account.client_id == SMART_TV

    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_login_rejects_a_new_account_when_registration_is_closed():
    engine, factory = await make_engine()
    settings = _settings(owner_twitch_id="", registration_open=False)

    async with factory() as session:
        await UserRepository(session).create(twitch_user_id="1", login="one")
        await session.commit()

        service = AuthService(
            session,
            settings=settings,
            provider=FakeTwitchProvider(_info(user_id="456")),
        )
        with pytest.raises(RegistrationClosedError):
            await service.complete_login(
                "token",
                _info(user_id="456"),
                invite_code="",
                current_user=None,
                client_id=ANDROID,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_login_rejects_a_different_signed_in_user():
    engine, factory = await make_engine()

    async with factory() as session:
        current = await UserRepository(session).create(
            twitch_user_id="1", login="one"
        )
        await UserRepository(session).create(twitch_user_id="456", login="other")
        await session.commit()

        service = AuthService(
            session,
            settings=_settings(),
            provider=FakeTwitchProvider(_info(user_id="456")),
        )
        with pytest.raises(AccountConflictError):
            await service.complete_login(
                "token",
                _info(user_id="456"),
                invite_code="",
                current_user=current,
                client_id=ANDROID,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_login_rejects_a_disabled_user():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        await UserRepository(session).set_active(user, False)
        await session.commit()

        service = AuthService(
            session,
            settings=_settings(),
            provider=FakeTwitchProvider(_info()),
        )
        with pytest.raises(AccountDisabledError):
            await service.complete_login(
                "token",
                _info(),
                invite_code="",
                current_user=None,
                client_id=ANDROID,
            )

    await engine.dispose()
