import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.domain.models import Campaign, DropProgress, Game, Stream
from app.services.scan_service import ScanService


class FakeSunkwi:
    def __init__(self, payload):
        self.payload = payload

    async def fetch_games(self):
        return self.payload


class FakeTwitch:
    ready = True

    async def get_streams(self, game_id, max_pages=5):
        return [
            {
                "user_login": "streamer",
                "user_name": "Streamer",
                "title": "Drops enabled",
                "viewer_count": 10,
                "language": "en",
                "started_at": "2026-01-01T00:00:00Z",
            }
        ]


class MultiStreamTwitch:
    ready = True

    async def get_streams(self, game_id, max_pages=5):
        return [
            {
                "user_login": login,
                "user_name": login.title(),
                "title": f"{login} drops",
                "viewer_count": 10,
                "language": "en",
                "started_at": "2026-01-01T00:00:00Z",
            }
            for login in ("alpha", "beta", "gamma")
        ]


class FakeTelegram:
    configured = False

    async def send(self, message):
        raise AssertionError("Telegram should not be used in this test")


class RecordingTelegram:
    configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, message):
        self.messages.append(message)


def payload():
    return {
        "games": [
            {
                "gameDisplayName": "Rust",
                "gameId": "263490",
                "campaigns": [
                    {
                        "id": 1,
                        "name": "Rust Drops",
                        "status": "ACTIVE",
                        "allow": {"isEnabled": False},
                        "timeBasedDrops": [
                            {
                                "name": "Skin",
                                "requiredMinutesWatched": 60,
                                "benefitEdges": [{"benefit": {"name": "Skin"}}],
                            }
                        ],
                    }
                ],
            },
            {
                "gameDisplayName": "Minecraft",
                "gameId": "27471",
                "campaigns": [
                    {
                        "id": 2,
                        "name": "Minecraft Drops",
                        "status": "ACTIVE",
                    }
                ],
            },
        ]
    }


@pytest.mark.asyncio
async def test_scan_persists_campaigns_for_all_games_and_streams_for_selected():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        settings = Settings(default_games="Rust", _env_file=None)
        service = ScanService(
            session=session,
            settings=settings,
            sunkwi=FakeSunkwi(payload()),
            twitch=FakeTwitch(),
            telegram=FakeTelegram(),
        )

        result = await service.run()

        assert result.campaign_count == 2
        assert result.stream_count == 1
        assert result.notified_count == 0

        campaign_total = await session.scalar(select(func.count()).select_from(Campaign))
        stream_total = await session.scalar(select(func.count()).select_from(Stream))
        selected_total = await session.scalar(
            select(func.count()).select_from(Game).where(Game.selected.is_(True))
        )

        assert campaign_total == 2
        assert stream_total == 1
        assert selected_total == 1

    await engine.dispose()


async def _scan_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def _run_scan(session, telegram):
    service = ScanService(
        session=session,
        settings=Settings(default_games="Rust", _env_file=None),
        sunkwi=FakeSunkwi(payload()),
        twitch=FakeTwitch(),
        telegram=telegram,
    )
    return await service.run()


@pytest.mark.asyncio
async def test_scan_alerts_only_for_in_progress_campaigns():
    engine, factory = await _scan_session()

    async with factory() as session:
        session.add(
            DropProgress(
                drop_id="drop-1",
                campaign_gql_id="1",
                campaign_name="Rust Drops",
                game_name="Rust",
            )
        )
        await session.commit()

        telegram = RecordingTelegram()
        result = await _run_scan(session, telegram)

        assert result.notified_count == 1
        assert len(telegram.messages) == 1
        assert "Rust Drops" in telegram.messages[0]
        assert "Minecraft Drops" not in telegram.messages[0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_suppresses_alerts_for_campaigns_not_in_progress():
    engine, factory = await _scan_session()

    async with factory() as session:
        session.add(
            DropProgress(
                drop_id="drop-1",
                campaign_gql_id="2",
                campaign_name="Minecraft Drops",
                game_name="Minecraft",
            )
        )
        await session.commit()

        telegram = RecordingTelegram()
        result = await _run_scan(session, telegram)

        assert result.notified_count == 0
        assert telegram.messages == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_digests_multiple_new_streams_once():
    engine, factory = await _scan_session()

    async with factory() as session:
        telegram = RecordingTelegram()
        service = ScanService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            sunkwi=FakeSunkwi(payload()),
            twitch=MultiStreamTwitch(),
            telegram=telegram,
        )

        first = await service.run()
        assert first.notified_count == 3
        assert len(telegram.messages) == 1
        message = telegram.messages[0]
        assert "3 eligible streams live" in message
        for login in ("alpha", "beta", "gamma"):
            assert login in message.lower()

        second = await service.run()
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_keeps_selected_game_alerts_without_progress_rows():
    engine, factory = await _scan_session()

    async with factory() as session:
        telegram = RecordingTelegram()
        result = await _run_scan(session, telegram)

        assert result.notified_count == 1
        assert len(telegram.messages) == 1
        assert "Rust Drops" in telegram.messages[0]

    await engine.dispose()
