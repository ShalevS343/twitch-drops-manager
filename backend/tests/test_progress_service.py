from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.domain.models import DropProgress, Notification
from app.repositories.twitch_auth import TwitchAuthRepository
from app.services.progress_service import ProgressService


class FakeProvider:
    async def fetch_inventory(self, access_token):
        return {
            "dropCampaignsInProgress": [
                {
                    "id": "campaign-1",
                    "name": "Test Campaign",
                    "endAt": "2026-12-01T00:00:00Z",
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
