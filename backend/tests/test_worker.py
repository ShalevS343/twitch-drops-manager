from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import hash_token
from app.domain.models import TwitchDeviceFlow, UserSession, UserWatchFocus
from app.worker import scheduler
from tests.support import connect_account, create_user, make_engine


class FakeScanService:
    def __init__(self) -> None:
        self.runs = 0

    async def run(self):
        self.runs += 1

        class Result:
            campaign_count = 0
            stream_count = 0
            notified_count = 0

        return Result()


class RecordingProgressService:
    def __init__(self, calls, user_id, fail_for=None) -> None:
        self.calls = calls
        self.user_id = user_id
        self.fail_for = fail_for

    async def run(self):
        self.calls.append(self.user_id)
        if self.user_id == self.fail_for:
            raise RuntimeError("boom")

        class Result:
            connected = True
            campaign_count = 0
            drop_count = 0
            notified_count = 0

        return Result()


class RecordingWatchService:
    def __init__(self, calls, user_id) -> None:
        self.calls = calls
        self.user_id = user_id

    async def reconcile(self):
        self.calls.append(self.user_id)

        class State:
            enabled = False
            status = "idle"
            focus = None

        return State()


@pytest.mark.asyncio
async def test_scan_job_prunes_expired_sessions(monkeypatch):
    engine, factory = await make_engine()
    scan = FakeScanService()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                UserSession(
                    user_id=user.id,
                    token_hash=hash_token("expired"),
                    expires_at=now - timedelta(hours=1),
                ),
                UserSession(
                    user_id=user.id,
                    token_hash=hash_token("valid"),
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(scheduler, "build_scan_service", lambda _session: scan)

    await scheduler.run_scan(session_factory=factory)

    assert scan.runs == 1
    async with factory() as session:
        rows = (await session.execute(select(UserSession))).scalars().all()
        assert [row.token_hash for row in rows] == [hash_token("valid")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_job_prunes_expired_device_flows(monkeypatch):
    engine, factory = await make_engine()
    scan = FakeScanService()

    async with factory() as session:
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                TwitchDeviceFlow(
                    flow_id="expired",
                    device_code="expired-code",
                    user_code="AAAA1111",
                    verification_uri="https://www.twitch.tv/activate",
                    client_id="client",
                    interval_seconds=5,
                    status="pending",
                    expires_at=now - timedelta(minutes=1),
                ),
                TwitchDeviceFlow(
                    flow_id="valid",
                    device_code="valid-code",
                    user_code="BBBB2222",
                    verification_uri="https://www.twitch.tv/activate",
                    client_id="client",
                    interval_seconds=5,
                    status="pending",
                    expires_at=now + timedelta(minutes=5),
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(scheduler, "build_scan_service", lambda _session: scan)

    await scheduler.run_scan(session_factory=factory)

    async with factory() as session:
        rows = (await session.execute(select(TwitchDeviceFlow))).scalars().all()
        assert [row.flow_id for row in rows] == ["valid"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_progress_job_continues_after_one_user_fails(monkeypatch):
    engine, factory = await make_engine()

    async with factory() as session:
        first = await create_user(session, twitch_user_id="1", login="first")
        second = await create_user(session, twitch_user_id="2", login="second")
        disconnected = await create_user(
            session, twitch_user_id="3", login="disconnected"
        )
        inactive = await create_user(
            session, twitch_user_id="4", login="inactive"
        )
        inactive.is_active = False
        for user in (first, second):
            await connect_account(session, user)
        await connect_account(session, inactive)
        await session.commit()

    calls: list[int] = []
    monkeypatch.setattr(
        scheduler,
        "build_progress_service",
        lambda _session, user_id: RecordingProgressService(
            calls, user_id, fail_for=first.id
        ),
    )

    await scheduler.run_progress(session_factory=factory)

    assert calls == [first.id, second.id]
    assert disconnected.id not in calls
    assert inactive.id not in calls

    await engine.dispose()


@pytest.mark.asyncio
async def test_watcher_job_only_loops_users_with_focus_enabled(monkeypatch):
    engine, factory = await make_engine()

    async with factory() as session:
        enabled = await create_user(session, twitch_user_id="1", login="enabled")
        disabled = await create_user(session, twitch_user_id="2", login="disabled")
        inactive = await create_user(session, twitch_user_id="3", login="inactive")
        inactive.is_active = False
        session.add_all(
            [
                UserWatchFocus(user_id=enabled.id, enabled=True),
                UserWatchFocus(user_id=disabled.id, enabled=False),
                UserWatchFocus(user_id=inactive.id, enabled=True),
            ]
        )
        await session.commit()

    calls: list[int] = []
    monkeypatch.setattr(
        scheduler,
        "build_watch_focus_service",
        lambda _session, user_id: RecordingWatchService(calls, user_id),
    )

    await scheduler.run_watcher(session_factory=factory)

    assert calls == [enabled.id]

    await engine.dispose()
