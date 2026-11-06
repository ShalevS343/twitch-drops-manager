import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.core.exceptions import ProviderError
from app.domain.models import Campaign, CampaignStart, DropProgress, Game, Stream
from app.repositories.games import GameRepository
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


async def _seed_campaign(
    session,
    *,
    game_name: str = "Rust",
    twitch_game_id: str = "263490",
    external_id: str = "Rust:1",
    status: str = "ACTIVE",
) -> None:
    game = Game(name=game_name, twitch_game_id=twitch_game_id, selected=True)
    session.add(game)
    await session.flush()
    session.add(
        Campaign(
            external_id=external_id,
            game_id=game.id,
            name=f"{game_name} Drops",
            status=status,
        )
    )
    await session.commit()


def warthunder_payload(status: str = "ACTIVE") -> dict:
    return {
        "games": [
            {
                "gameDisplayName": "War Thunder",
                "gameId": "66366",
                "campaigns": [
                    {
                        "id": "wt-1",
                        "name": "WT Campaign",
                        "status": status,
                        "allow": {"isEnabled": False},
                    }
                ],
            }
        ]
    }


class FlakyTelegram:
    configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.fail_next = True

    async def send(self, message):
        if self.fail_next:
            self.fail_next = False
            raise ProviderError("simulated Telegram failure")
        self.messages.append(message)


@pytest.mark.asyncio
async def test_scan_does_not_notify_new_streams():
    engine, factory = await _scan_session()

    async with factory() as session:
        await _seed_campaign(session, status="UPCOMING")
        telegram = RecordingTelegram()
        service = ScanService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            sunkwi=FakeSunkwi(payload()),
            twitch=MultiStreamTwitch(),
            telegram=telegram,
        )

        first = await service.run()
        assert first.notified_count == 1  # campaign start only
        assert len(telegram.messages) == 1
        message = telegram.messages[0]
        assert "New campaign:" in message
        assert "Live now" not in message
        for login in ("alpha", "beta", "gamma"):
            assert login not in message.lower()

        second = await service.run()
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_does_not_notify_streams_without_a_campaign_start():
    engine, factory = await _scan_session()

    async with factory() as session:
        # The campaign is already ACTIVE, so this scan has no start event.
        await _seed_campaign(session)
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

        assert result.notified_count == 0
        assert telegram.messages == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_notifies_when_campaign_starts():
    engine, factory = await _scan_session()

    async with factory() as session:
        telegram = RecordingTelegram()
        result = await _run_scan(session, telegram)

        assert result.notified_count == 1  # campaign start only
        assert len(telegram.messages) == 1
        message = telegram.messages[0]
        assert "New campaign:" in message
        assert "Rust Drops" in message
        assert "Live now" not in message

        starts = await session.scalar(select(func.count()).select_from(CampaignStart))
        assert starts == 0

        second = await _run_scan(session, telegram)
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_notifies_when_upcoming_campaign_becomes_active():
    engine, factory = await _scan_session()

    async with factory() as session:
        await _seed_campaign(
            session,
            game_name="War Thunder",
            twitch_game_id="66366",
            external_id="War Thunder:wt-1",
            status="UPCOMING",
        )
        telegram = RecordingTelegram()
        service = ScanService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            sunkwi=FakeSunkwi(warthunder_payload("ACTIVE")),
            twitch=FakeTwitch(),
            telegram=telegram,
        )

        result = await service.run()

        assert result.notified_count == 1
        assert "New campaign:" in telegram.messages[0]
        assert "WT Campaign" in telegram.messages[0]
        assert "Live now" not in telegram.messages[0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_notifies_for_game_added_by_name():
    engine, factory = await _scan_session()

    async with factory() as session:
        await GameRepository(session).set_selected(["War Thunder"])
        await session.commit()

        telegram = RecordingTelegram()
        service = ScanService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            sunkwi=FakeSunkwi(warthunder_payload("ACTIVE")),
            twitch=FakeTwitch(),
            telegram=telegram,
        )

        result = await service.run()

        assert result.notified_count == 1
        assert "New campaign:" in telegram.messages[0]
        assert "War Thunder" in telegram.messages[0]
        assert "Live now" not in telegram.messages[0]

        game = await session.scalar(
            select(Game).where(Game.name == "War Thunder")
        )
        assert game is not None
        assert game.selected is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_does_not_notify_untracked_game_start():
    engine, factory = await _scan_session()

    async with factory() as session:
        payload = {
            "games": [
                {
                    "gameDisplayName": "Minecraft",
                    "gameId": "27471",
                    "campaigns": [
                        {
                            "id": "mc-1",
                            "name": "Minecraft Drops",
                            "status": "ACTIVE",
                        }
                    ],
                }
            ]
        }
        telegram = RecordingTelegram()
        service = ScanService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            sunkwi=FakeSunkwi(payload),
            twitch=FakeTwitch(),
            telegram=telegram,
        )

        result = await service.run()

        assert result.notified_count == 0
        assert telegram.messages == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_retries_campaign_start_after_send_failure():
    engine, factory = await _scan_session()

    async with factory() as session:
        telegram = FlakyTelegram()
        service = ScanService(
            session=session,
            settings=Settings(default_games="Rust", _env_file=None),
            sunkwi=FakeSunkwi(payload()),
            twitch=FakeTwitch(),
            telegram=telegram,
        )

        first = await service.run()
        assert first.notified_count == 0
        assert telegram.messages == []
        starts = await session.scalar(select(func.count()).select_from(CampaignStart))
        assert starts == 1

        second = await service.run()
        assert second.notified_count == 1
        assert len(telegram.messages) == 1
        assert "New campaign:" in telegram.messages[0]
        starts = await session.scalar(select(func.count()).select_from(CampaignStart))
        assert starts == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_set_selected_creates_tracked_game_without_campaign():
    engine, factory = await _scan_session()

    async with factory() as session:
        selected = await GameRepository(session).set_selected(["War Thunder"])
        await session.commit()

        assert [game.name for game in selected] == ["War Thunder"]
        game = await session.scalar(select(Game).where(Game.name == "War Thunder"))
        assert game is not None
        assert game.selected is True
        assert game.box_art_url == ""

    await engine.dispose()
