"""Device flow repository/service lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.db import Base
from app.core.exceptions import (
    AccountConflictError,
    DeviceFlowAccessDeniedError,
    DeviceFlowDeniedError,
    DeviceFlowExpiredError,
    DeviceFlowExpiredTokenError,
    DeviceFlowNotFoundError,
    DeviceFlowPendingError,
    DeviceFlowSlowDownError,
    ProviderError,
    RegistrationClosedError,
)
from app.domain.models import TwitchAccount, TwitchDeviceFlow
from app.repositories.twitch_device_flows import TwitchDeviceFlowRepository
from app.repositories.users import UserRepository
from app.services.twitch_device_service import TwitchDeviceService
from tests.support import create_user, make_engine

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
        self.poll_calls = 0
        self.info = {
            "client_id": SMART_TV,
            "user_id": "123",
            "login": "viewer",
            "expires_in": 3600,
        }
        self.profile_calls = []

    async def start_device_flow(self):
        return dict(self.start_response)

    async def poll_device_token(self, device_code, client_id):
        self.poll_calls += 1
        result = self.poll_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def validate(self, _token):
        return dict(self.info)

    async def fetch_profile(self, access_token, user_id="", client_id=""):
        self.profile_calls.append((access_token, user_id, client_id))
        return {}


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "registration_open": True,
        "registration_code": "",
        "owner_twitch_id": "",
        "default_games": "",
        "twitch_device_grant_client_id": SMART_TV,
        "twitch_device_client_id": "android-client",
    }
    values.update(overrides)
    return Settings(**values)


async def _service(session, provider=None, **settings_overrides):
    return TwitchDeviceService(
        session,
        settings=_settings(**settings_overrides),
        provider=provider or FakeDeviceProvider(),
    )


@pytest.mark.asyncio
async def test_start_creates_a_short_lived_flow_without_exposing_device_code():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()

    async with factory() as session:
        user = await create_user(session)
        await session.commit()

        started = await (await _service(session, provider)).start(
            invite_code="invite-1", current_user=user
        )

        assert started.user_code == "ABCD1234"
        assert started.verification_uri == "https://www.twitch.tv/activate"
        assert started.interval == 5
        assert started.flow_id
        assert started.expires_at > datetime.now(timezone.utc)
        assert "device-secret" not in repr(started)

        flow = (
            await session.execute(select(TwitchDeviceFlow))
        ).scalar_one()
        assert flow.flow_id == started.flow_id
        assert flow.device_code == "device-secret"
        assert flow.client_id == SMART_TV
        assert flow.invite_code == "invite-1"
        assert flow.current_user_id == user.id
        assert flow.status == "pending"

    await engine.dispose()


@pytest.mark.asyncio
async def test_start_clamps_ttl_to_thirty_minutes():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.start_response["expires_in"] = 999_999

    async with factory() as session:
        before = datetime.now(timezone.utc)
        started = await (await _service(session, provider)).start()
        assert started.expires_at <= before + timedelta(minutes=30, seconds=5)

    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_poll_returns_interval_and_throttles_duplicate_polls():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [DeviceFlowPendingError("pending")]

    async with factory() as session:
        service = await _service(session, provider)
        started = await service.start()

        first = await service.poll(started.flow_id)
        assert first.pending is True
        assert first.interval == 5
        assert provider.poll_calls == 1

        second = await service.poll(started.flow_id)
        assert second.pending is True
        assert second.interval == 5
        assert provider.poll_calls == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_transient_upstream_failure_stays_pending_and_respects_cadence():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [ProviderError("network down")]

    async with factory() as session:
        service = await _service(session, provider)
        started = await service.start()

        result = await service.poll(started.flow_id)
        assert result.pending is True
        assert result.interval == 5
        assert provider.poll_calls == 1

        flow = (
            await session.execute(select(TwitchDeviceFlow))
        ).scalar_one()
        assert flow.status == "pending"

        # The transient failure still consumed this cadence slot.
        again = await service.poll(started.flow_id)
        assert again.pending is True
        assert provider.poll_calls == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_slow_down_increases_and_persists_the_interval():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [DeviceFlowSlowDownError("slow down")]

    async with factory() as session:
        service = await _service(session, provider)
        started = await service.start()

        result = await service.poll(started.flow_id)
        assert result.pending is True
        assert result.interval == 10

        flow = (
            await session.execute(select(TwitchDeviceFlow))
        ).scalar_one()
        assert flow.interval_seconds == 10

        # A duplicate poll is still throttled at the new interval.
        again = await service.poll(started.flow_id)
        assert again.interval == 10
        assert provider.poll_calls == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_success_creates_session_and_stores_the_smart_tv_client():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [
        {"access_token": "access-token", "expires_in": 3600}
    ]

    async with factory() as session:
        service = await _service(session, provider)
        started = await service.start()

        result = await service.poll(started.flow_id)

        assert result.pending is False
        assert result.auth is not None
        assert result.auth.created is True
        assert result.auth.user.twitch_user_id == "123"
        assert result.auth.session_token

        account = (
            await session.execute(select(TwitchAccount))
        ).scalar_one()
        assert account.access_token == "access-token"
        assert account.client_id == SMART_TV
        assert provider.profile_calls == [("access-token", "123", SMART_TV)]

        flow = (
            await session.execute(select(TwitchDeviceFlow))
        ).scalar_one()
        assert flow.status == "connected"

        with pytest.raises(DeviceFlowNotFoundError):
            await service.poll(started.flow_id)

    await engine.dispose()


@pytest.mark.asyncio
async def test_denied_flow_becomes_terminal():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [DeviceFlowAccessDeniedError("denied")]

    async with factory() as session:
        service = await _service(session, provider)
        started = await service.start()

        with pytest.raises(DeviceFlowDeniedError):
            await service.poll(started.flow_id)

        flow = (
            await session.execute(select(TwitchDeviceFlow))
        ).scalar_one()
        assert flow.status == "denied"

        with pytest.raises(DeviceFlowNotFoundError):
            await service.poll(started.flow_id)

    await engine.dispose()


@pytest.mark.asyncio
async def test_upstream_expired_token_becomes_terminal():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [DeviceFlowExpiredTokenError("expired")]

    async with factory() as session:
        service = await _service(session, provider)
        started = await service.start()

        with pytest.raises(DeviceFlowExpiredError):
            await service.poll(started.flow_id)

        flow = (
            await session.execute(select(TwitchDeviceFlow))
        ).scalar_one()
        assert flow.status == "expired"

    await engine.dispose()


@pytest.mark.asyncio
async def test_locally_expired_flow_is_rejected_without_polling_twitch():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()

    async with factory() as session:
        service = await _service(session, provider)
        started = await service.start()
        flow = (
            await session.execute(select(TwitchDeviceFlow))
        ).scalar_one()
        flow.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(DeviceFlowExpiredError):
            await service.poll(started.flow_id)
        assert provider.poll_calls == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_deletes_the_flow():
    engine, factory = await make_engine()

    async with factory() as session:
        service = await _service(session)
        started = await service.start()

        await service.cancel(started.flow_id)

        assert (
            await session.execute(select(TwitchDeviceFlow))
        ).scalars().all() == []
        with pytest.raises(DeviceFlowNotFoundError):
            await service.poll(started.flow_id)

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_expired_removes_only_expired_rows():
    engine, factory = await make_engine()

    async with factory() as session:
        repo = TwitchDeviceFlowRepository(session)
        now = datetime.now(timezone.utc)
        await repo.create(
            flow_id="expired",
            device_code="expired-code",
            user_code="AAAA1111",
            verification_uri="https://www.twitch.tv/activate",
            client_id=SMART_TV,
            invite_code="",
            current_user_id=None,
            interval_seconds=5,
            expires_at=now - timedelta(minutes=1),
        )
        await repo.create(
            flow_id="valid",
            device_code="valid-code",
            user_code="BBBB2222",
            verification_uri="https://www.twitch.tv/activate",
            client_id=SMART_TV,
            invite_code="",
            current_user_id=None,
            interval_seconds=5,
            expires_at=now + timedelta(minutes=5),
        )
        await session.commit()

        deleted = await repo.delete_expired()
        await session.commit()

        assert deleted == 1
        assert [row.flow_id for row in (
            await session.execute(select(TwitchDeviceFlow))
        ).scalars().all()] == ["valid"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_gate_runs_on_the_eventual_twitch_user():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [
        {"access_token": "access-token", "expires_in": 3600}
    ]

    async with factory() as session:
        await create_user(session, twitch_user_id="1", login="owner")
        await session.commit()
        service = await _service(
            session,
            provider,
            registration_open=False,
            owner_twitch_id="",
            registration_code="secret",
        )
        started = await service.start(invite_code="wrong")

        with pytest.raises(RegistrationClosedError):
            await service.poll(started.flow_id)

    await engine.dispose()


@pytest.mark.asyncio
async def test_current_user_conflict_is_preserved_by_the_device_flow():
    engine, factory = await make_engine()
    provider = FakeDeviceProvider()
    provider.poll_results = [
        {"access_token": "access-token", "expires_in": 3600}
    ]

    async with factory() as session:
        current = await create_user(session, twitch_user_id="1", login="one")
        await UserRepository(session).create(twitch_user_id="123", login="viewer")
        await session.commit()
        service = await _service(session, provider)
        started = await service.start(current_user=current)

        with pytest.raises(AccountConflictError):
            await service.poll(started.flow_id)

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_polls_claim_one_upstream_slot(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'device.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    provider = FakeDeviceProvider()
    provider.poll_results = [DeviceFlowPendingError("pending")]

    async with factory() as session:
        started = await TwitchDeviceService(
            session, settings=_settings(), provider=provider
        ).start()
        flow_id = started.flow_id

    async def poll_once():
        async with factory() as session:
            return await TwitchDeviceService(
                session, settings=_settings(), provider=provider
            ).poll(flow_id)

    results = await asyncio.gather(poll_once(), poll_once())

    assert all(result.pending for result in results)
    assert provider.poll_calls == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_connected_status_is_never_downgraded():
    engine, factory = await make_engine()

    async with factory() as session:
        repo = TwitchDeviceFlowRepository(session)
        flow = await repo.create(
            flow_id="done",
            device_code="device-code",
            user_code="AAAA1111",
            verification_uri="https://www.twitch.tv/activate",
            client_id=SMART_TV,
            invite_code="",
            current_user_id=None,
            interval_seconds=5,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            status="connected",
        )
        await session.commit()

        assert await repo.set_status(flow.flow_id, "expired") is False
        await session.commit()

        refreshed = await repo.get_by_flow_id(flow.flow_id)
        assert refreshed is not None
        assert refreshed.status == "connected"

    await engine.dispose()
