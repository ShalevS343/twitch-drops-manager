import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.domain.models import Campaign, Game, Stream
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


class FakeTelegram:
    configured = False

    async def send(self, message):
        raise AssertionError("Telegram should not be used in this test")


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
