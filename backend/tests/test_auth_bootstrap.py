"""First-run bootstrap gates (H-1)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.db import Base
from app.core.exceptions import RegistrationClosedError
from app.repositories.users import UserRepository
from app.services.auth_service import AuthService, RegistrationState
from tests.support import make_engine


class FakeTwitchProvider:
    def __init__(self, *, user_id: str = "123", login: str = "viewer") -> None:
        self.info = {
            "client_id": "client",
            "user_id": user_id,
            "login": login,
            "expires_in": 3600,
        }

    def parse_oauth_token(self, _value):
        return "token"

    async def validate(self, _token):
        return dict(self.info)

    async def fetch_profile(self, _access_token, _user_id="", client_id=""):
        return {}


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "registration_code": "",
        "registration_open": False,
        "owner_twitch_id": "",
        "default_games": "",
        "twitch_gql_client_id": "client",
        "twitch_device_client_id": "client",
    }
    values.update(overrides)
    return Settings(**values)


async def _connect(session, settings, *, user_id: str = "123", code: str = ""):
    return await AuthService(
        session,
        settings=settings,
        provider=FakeTwitchProvider(user_id=user_id),
    ).connect("url", code)


@pytest.mark.asyncio
async def test_first_user_is_rejected_without_a_bootstrap_gate():
    engine, factory = await make_engine()

    async with factory() as session:
        service = AuthService(
            session, settings=_settings(), provider=FakeTwitchProvider()
        )
        assert await service.registration_state() == RegistrationState(
            open=False, invite_required=False
        )

        with pytest.raises(RegistrationClosedError):
            await _connect(session, _settings())

        assert await UserRepository(session).count() == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_first_user_matching_owner_twitch_id_becomes_admin():
    engine, factory = await make_engine()
    settings = _settings(owner_twitch_id="123")

    async with factory() as session:
        result = await _connect(session, settings, user_id="123")
        assert result.created is True
        assert result.user.role == "admin"
        assert result.user.twitch_user_id == "123"
        assert await UserRepository(session).count() == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_first_user_not_matching_owner_twitch_id_is_rejected():
    engine, factory = await make_engine()
    settings = _settings(owner_twitch_id="999")

    async with factory() as session:
        with pytest.raises(RegistrationClosedError):
            await _connect(session, settings, user_id="123")

        assert await UserRepository(session).count() == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_first_user_via_invite_code_then_second_user_needs_it():
    engine, factory = await make_engine()
    settings = _settings(registration_code="secret")

    async with factory() as session:
        with pytest.raises(RegistrationClosedError):
            await _connect(session, settings, user_id="123", code="")

        with pytest.raises(RegistrationClosedError):
            await _connect(session, settings, user_id="123", code="wrong")

        first = await _connect(session, settings, user_id="123", code="secret")
        assert first.user.role == "admin"

        with pytest.raises(RegistrationClosedError):
            await _connect(session, settings, user_id="456", code="")

        second = await _connect(session, settings, user_id="456", code="secret")
        assert second.user.role == "user"

    await engine.dispose()


@pytest.mark.asyncio
async def test_first_user_via_explicit_open_registration():
    engine, factory = await make_engine()
    settings = _settings(registration_open=True)

    async with factory() as session:
        result = await _connect(session, settings, user_id="123")
        assert result.created is True
        assert result.user.role == "admin"

    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, RegistrationState(open=False, invite_required=False)),
        (
            {"owner_twitch_id": "123"},
            RegistrationState(open=True, invite_required=False),
        ),
        (
            {"registration_open": True},
            RegistrationState(open=True, invite_required=False),
        ),
        (
            {"registration_code": "secret"},
            RegistrationState(open=True, invite_required=True),
        ),
    ],
)
async def test_empty_database_registration_state_reports_only_available_gates(
    overrides, expected
):
    engine, factory = await make_engine()

    async with factory() as session:
        service = AuthService(
            session,
            settings=_settings(**overrides),
            provider=FakeTwitchProvider(),
        )
        assert await service.registration_state() == expected

    await engine.dispose()


async def _file_engine(path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_concurrent_first_users_produce_exactly_one_admin(tmp_path):
    engine, factory = await _file_engine(tmp_path / "concurrent.db")
    settings = _settings(registration_open=True)

    async def register(user_id: str, login: str):
        async with factory() as session:
            return await _connect(session, settings, user_id=user_id)

    first, second = await asyncio.gather(
        register("1", "first"), register("2", "second")
    )

    roles = sorted([first.user.role, second.user.role])
    assert roles == ["admin", "user"]

    async with factory() as session:
        users = await UserRepository(session).list()
        assert len(users) == 2
        assert sum(1 for user in users if user.role == "admin") == 1

    await engine.dispose()
