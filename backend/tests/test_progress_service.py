from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.progress import list_progress
from app.core.config import Settings
from app.core.db import Base
from app.core.exceptions import ProviderError
from app.domain.models import DropProgress, Notification, ProgressSnapshot
from app.repositories.twitch_auth import TwitchAuthRepository
from app.services.progress_service import ProgressService


class FakeProvider:
    async def fetch_inventory(self, access_token):
        return {
            "dropCampaignsInProgress": [
                {
                    "id": "campaign-1",
                    "name": "Test Campaign",
                    # Keep this outside the 24h deadline-reminder window so the
                    # test only exercises the ready-to-claim notification.
                    "endAt": "2099-12-01T00:00:00Z",
                    "game": {
                        "displayName": "Rust",
                        "boxArtURL": "https://example.test/rust.jpg",
                    },
                    "timeBasedDrops": [
                        {
                            "id": "drop-1",
                            "name": "First Drop",
                            "requiredMinutesWatched": 60,
                            "startAt": "2026-11-01T00:00:00Z",
                            "endAt": "2026-12-01T00:00:00Z",
                            "benefitEdges": [{"benefit": {"name": "Skin"}}],
                            "self": {
                                "dropInstanceID": "instance-1",
                                "isClaimed": False,
                                "currentMinutesWatched": 60,
                            },
                        },
                        {
                            "id": "drop-2",
                            "name": "Second Drop",
                            "requiredMinutesWatched": 120,
                            "benefitEdges": [],
                            "self": {
                                "dropInstanceID": "instance-2",
                                "isClaimed": False,
                                "currentMinutesWatched": 30,
                            },
                        },
                    ],
                }
            ]
        }

    async def refresh(self, refresh_token):
        raise AssertionError("Token should not need refreshing in this test")


class FakeTelegram:
    configured = True

    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(message)


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


@pytest.mark.asyncio
async def test_progress_sync_persists_drops_and_notifies_once():
    engine, factory = await _session()
    telegram = FakeTelegram()

    async with factory() as session:
        await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await session.commit()

        service = ProgressService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            provider=FakeProvider(),
            telegram=telegram,
        )

        first = await service.run()
        assert first.connected is True
        assert first.campaign_count == 1
        assert first.drop_count == 2
        assert first.notified_count == 1
        assert len(telegram.messages) == 1
        assert "First Drop" in telegram.messages[0]
        assert "https://www.twitch.tv/drops/inventory" in telegram.messages[0]

        total = await session.scalar(select(func.count()).select_from(DropProgress))
        assert total == 2
        ready = await session.scalar(
            select(func.count()).select_from(DropProgress).where(
                DropProgress.is_ready.is_(True)
            )
        )
        assert ready == 1

        # A second sync must not re-send the same "ready to claim" message.
        second = await service.run()
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

        notification_total = await session.scalar(
            select(func.count()).select_from(Notification)
        )
        assert notification_total == 1

    await engine.dispose()


def _drop_row(
    drop_id: str,
    *,
    required: int,
    current: int,
    claimed: bool = False,
    drop_name: str | None = None,
) -> DropProgress:
    return DropProgress(
        drop_id=drop_id,
        drop_name=drop_name or drop_id,
        campaign_gql_id="campaign-1",
        campaign_name="Test Campaign",
        campaign_ends_at="2026-12-01T00:00:00Z",
        game_name="Rust",
        required_minutes=required,
        current_minutes=current,
        is_claimed=claimed,
        is_ready=required > 0 and current >= required and not claimed,
    )


@pytest.mark.asyncio
async def test_progress_api_computes_rate_and_eta_from_snapshots():
    engine, factory = await _session()

    async with factory() as session:
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                _drop_row("drop-fast", required=120, current=60),
                _drop_row("drop-quick", required=60, current=30),
                _drop_row("drop-claimed", required=30, current=30, claimed=True),
            ]
        )
        session.add_all(
            [
                ProgressSnapshot(
                    drop_id="drop-fast",
                    current_minutes=30,
                    recorded_at=now - timedelta(minutes=60),
                ),
                ProgressSnapshot(
                    drop_id="drop-fast", current_minutes=60, recorded_at=now
                ),
                ProgressSnapshot(
                    drop_id="drop-quick",
                    current_minutes=0,
                    recorded_at=now - timedelta(minutes=60),
                ),
                ProgressSnapshot(
                    drop_id="drop-quick", current_minutes=60, recorded_at=now
                ),
            ]
        )
        await session.commit()

        campaigns = await list_progress(session)

        assert len(campaigns) == 1
        campaign = campaigns[0]
        assert campaign.remaining_minutes == 90
        assert campaign.eta_minutes == 150

        drops = {drop.drop_id: drop for drop in campaign.drops}
        assert drops["drop-fast"].remaining_minutes == 60
        assert drops["drop-fast"].rate_minutes_per_hour == pytest.approx(30.0)
        assert drops["drop-fast"].eta_minutes == 120

        assert drops["drop-quick"].remaining_minutes == 30
        assert drops["drop-quick"].rate_minutes_per_hour == pytest.approx(60.0)
        assert drops["drop-quick"].eta_minutes == 30

        assert drops["drop-claimed"].remaining_minutes == 0
        assert drops["drop-claimed"].eta_minutes is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_progress_api_ignores_slow_watch_rate():
    engine, factory = await _session()

    async with factory() as session:
        now = datetime.now(timezone.utc)
        session.add(_drop_row("drop-slow", required=60, current=30))
        session.add_all(
            [
                ProgressSnapshot(
                    drop_id="drop-slow",
                    current_minutes=30,
                    recorded_at=now - timedelta(minutes=60),
                ),
                ProgressSnapshot(
                    drop_id="drop-slow", current_minutes=30, recorded_at=now
                ),
            ]
        )
        await session.commit()

        campaigns = await list_progress(session)

        drop = campaigns[0].drops[0]
        assert drop.remaining_minutes == 30
        assert drop.rate_minutes_per_hour is None
        assert drop.eta_minutes is None
        assert campaigns[0].eta_minutes is None

    await engine.dispose()


class DeadlineProvider:
    def __init__(self, end_at: str) -> None:
        self.end_at = end_at

    async def fetch_inventory(self, access_token):
        return {
            "dropCampaignsInProgress": [
                {
                    "id": "campaign-1",
                    "name": "Test Campaign",
                    "endAt": self.end_at,
                    "game": {"displayName": "Rust"},
                    "timeBasedDrops": [
                        {
                            "id": "drop-1",
                            "name": "First Drop",
                            "requiredMinutesWatched": 60,
                            "self": {
                                "isClaimed": False,
                                "currentMinutesWatched": 0,
                            },
                        }
                    ],
                }
            ]
        }

    async def refresh(self, refresh_token):
        raise AssertionError("Token should not need refreshing in this test")


@pytest.mark.asyncio
async def test_progress_service_sends_campaign_deadline_reminders_once():
    engine, factory = await _session()
    telegram = FakeTelegram()

    async with factory() as session:
        await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await session.commit()

        end_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        service = ProgressService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            provider=DeadlineProvider(end_at),
            telegram=telegram,
        )

        first = await service.run()
        assert first.notified_count == 1
        assert len(telegram.messages) == 1
        assert "Test Campaign" in telegram.messages[0]
        assert "ends in ~2h" in telegram.messages[0]
        assert "1 drops left (60 min)" in telegram.messages[0]

        snapshot_total = await session.scalar(
            select(func.count()).select_from(ProgressSnapshot)
        )
        assert snapshot_total == 1

        keys = set(
            (await session.execute(select(Notification.dedupe_key))).scalars().all()
        )
        assert keys == {"campaign-ending:campaign-1:2h"}

        second = await service.run()
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

    await engine.dispose()


class TwoReadyDropsProvider:
    async def fetch_inventory(self, access_token):
        return {
            "dropCampaignsInProgress": [
                {
                    "id": "campaign-1",
                    "name": "Test Campaign",
                    "endAt": "2099-12-01T00:00:00Z",
                    "game": {"displayName": "Rust"},
                    "timeBasedDrops": [
                        {
                            "id": "drop-1",
                            "name": "First Drop",
                            "requiredMinutesWatched": 60,
                            "self": {
                                "isClaimed": False,
                                "currentMinutesWatched": 60,
                            },
                        },
                        {
                            "id": "drop-2",
                            "name": "Second Drop",
                            "requiredMinutesWatched": 30,
                            "self": {
                                "isClaimed": False,
                                "currentMinutesWatched": 30,
                            },
                        },
                    ],
                }
            ]
        }

    async def refresh(self, refresh_token):
        raise AssertionError("Token should not need refreshing in this test")


@pytest.mark.asyncio
async def test_progress_service_digests_multiple_ready_drops_once():
    engine, factory = await _session()
    telegram = FakeTelegram()

    async with factory() as session:
        await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await session.commit()

        service = ProgressService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            provider=TwoReadyDropsProvider(),
            telegram=telegram,
        )

        first = await service.run()
        assert first.notified_count == 2
        assert len(telegram.messages) == 1
        assert "First Drop" in telegram.messages[0]
        assert "Second Drop" in telegram.messages[0]

        second = await service.run()
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

        keys = set(
            (await session.execute(select(Notification.dedupe_key))).scalars().all()
        )
        assert keys == {"drop-ready:drop-1", "drop-ready:drop-2"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_progress_service_uses_24h_window_when_campaign_ends_in_10h():
    engine, factory = await _session()
    telegram = FakeTelegram()

    async with factory() as session:
        await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await session.commit()

        end_at = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
        service = ProgressService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            provider=DeadlineProvider(end_at),
            telegram=telegram,
        )

        result = await service.run()
        assert result.notified_count == 1
        assert len(telegram.messages) == 1
        assert "ends in ~24h" in telegram.messages[0]

        keys = set(
            (await session.execute(select(Notification.dedupe_key))).scalars().all()
        )
        assert keys == {"campaign-ending:campaign-1:24h"}

    await engine.dispose()


class FlakyTelegram:
    configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.failures = 1

    async def send(self, message):
        if self.failures:
            self.failures -= 1
            raise ProviderError("telegram unavailable")
        self.messages.append(message)


@pytest.mark.asyncio
async def test_progress_service_releases_claim_when_send_fails():
    engine, factory = await _session()
    telegram = FlakyTelegram()

    async with factory() as session:
        await TwitchAuthRepository(session).save(
            user_id="123",
            login="viewer",
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await session.commit()

        end_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        service = ProgressService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            provider=DeadlineProvider(end_at),
            telegram=telegram,
        )

        first = await service.run()
        assert first.notified_count == 0
        assert telegram.messages == []
        notification_total = await session.scalar(
            select(func.count()).select_from(Notification)
        )
        assert notification_total == 0

        second = await service.run()
        assert second.notified_count == 1
        assert len(telegram.messages) == 1
        assert "ends in ~2h" in telegram.messages[0]

    await engine.dispose()
