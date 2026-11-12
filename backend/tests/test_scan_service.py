import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.core.security import create_auth_session
from app.domain.models import (
    Campaign,
    Game,
    Stream,
    UserCampaignStart,
    UserGame,
    UserSession,
)
from app.repositories.user_games import UserGameRepository
from app.services.scan_service import ScanService
from tests.support import create_user, make_engine


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

    async def send(self, message, chat_id):
        raise AssertionError("Telegram should not be used in this test")


class RecordingTelegram:
    configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.chat_ids: list[str] = []

    async def send(self, message, chat_id):
        self.messages.append(message)
        self.chat_ids.append(chat_id)


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


async def _scan_session():
    return await make_engine()


async def _seed_user(
    session,
    *,
    twitch_user_id: str = "1",
    login: str = "viewer",
    games: tuple[str, ...] = ("Rust",),
    telegram_chat_id: str = "111",
    telegram_enabled: bool = True,
):
    user = await create_user(
        session,
        twitch_user_id=twitch_user_id,
        login=login,
        telegram_chat_id=telegram_chat_id,
        telegram_enabled=telegram_enabled,
    )
    await UserGameRepository(session).replace(user.id, list(games))
    await session.commit()
    return user


def _service(session, telegram, *, twitch=None, payload_data=None):
    return ScanService(
        session=session,
        settings=Settings(default_games="Rust", _env_file=None),
        sunkwi=FakeSunkwi(payload_data or payload()),
        twitch=twitch or FakeTwitch(),
        telegram=telegram,
    )


@pytest.mark.asyncio
async def test_scan_persists_campaigns_for_all_games_and_streams_for_selected():
    engine, factory = await _scan_session()

    async with factory() as session:
        user = await _seed_user(session)
        service = _service(session, FakeTelegram())

        result = await service.run()

        assert result.campaign_count == 2
        assert result.stream_count == 1
        assert result.notified_count == 0

        campaign_total = await session.scalar(select(func.count()).select_from(Campaign))
        stream_total = await session.scalar(select(func.count()).select_from(Stream))
        selected_total = await session.scalar(
            select(func.count())
            .select_from(UserGame)
            .where(UserGame.user_id == user.id)
        )

        assert campaign_total == 2
        assert stream_total == 1
        assert selected_total == 1

    await engine.dispose()


async def _run_scan(session, telegram, *, twitch=None, payload_data=None):
    return await _service(
        session, telegram, twitch=twitch, payload_data=payload_data
    ).run()


@pytest.mark.asyncio
async def test_scan_prunes_expired_sessions():
    engine, factory = await _scan_session()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="123", login="viewer")
        await create_auth_session(session, user.id, ttl_days=-1)
        await create_auth_session(session, user.id, ttl_days=30)
        await session.commit()

        await _run_scan(session, FakeTelegram())

        remaining = (await session.execute(select(UserSession))).scalars().all()
        assert len(remaining) == 1

    await engine.dispose()


async def _seed_campaign(
    session,
    *,
    game_name: str = "Rust",
    twitch_game_id: str = "263490",
    external_id: str = "Rust:1",
    status: str = "ACTIVE",
) -> None:
    game = Game(name=game_name, twitch_game_id=twitch_game_id)
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

    def __init__(self, failures: int = 1) -> None:
        self.messages: list[str] = []
        self.chat_ids: list[str] = []
        self.attempted_chat_ids: list[str] = []
        self.failures = failures

    async def send(self, message, chat_id):
        self.attempted_chat_ids.append(chat_id)
        if self.failures:
            self.failures -= 1
            raise ProviderError("simulated Telegram failure")
        self.messages.append(message)
        self.chat_ids.append(chat_id)


@pytest.mark.asyncio
async def test_scan_does_not_notify_new_streams():
    engine, factory = await _scan_session()

    async with factory() as session:
        await _seed_campaign(session, status="UPCOMING")
        await _seed_user(session)
        telegram = RecordingTelegram()

        first = await _run_scan(
            session, telegram, twitch=MultiStreamTwitch()
        )
        assert first.notified_count == 1  # campaign start only
        assert len(telegram.messages) == 1
        message = telegram.messages[0]
        assert "New campaign:" in message
        assert "Live now" not in message
        for login in ("alpha", "beta", "gamma"):
            assert login not in message.lower()

        second = await _run_scan(
            session, telegram, twitch=MultiStreamTwitch()
        )
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_does_not_notify_streams_without_a_campaign_start():
    engine, factory = await _scan_session()

    async with factory() as session:
        # The campaign is already ACTIVE, so this scan has no start event.
        await _seed_campaign(session)
        await _seed_user(session)

        telegram = RecordingTelegram()
        result = await _run_scan(session, telegram)

        assert result.notified_count == 0
        assert telegram.messages == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_notifies_when_campaign_starts():
    engine, factory = await _scan_session()

    async with factory() as session:
        await _seed_user(session)
        telegram = RecordingTelegram()
        result = await _run_scan(session, telegram)

        assert result.notified_count == 1  # campaign start only
        assert len(telegram.messages) == 1
        assert telegram.chat_ids == ["111"]
        message = telegram.messages[0]
        assert "New campaign:" in message
        assert "Rust Drops" in message
        assert "Live now" not in message

        starts = await session.scalar(
            select(func.count()).select_from(UserCampaignStart)
        )
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
        await _seed_user(session, games=("War Thunder",))
        telegram = RecordingTelegram()

        result = await _run_scan(
            session,
            telegram,
            payload_data=warthunder_payload("ACTIVE"),
        )

        assert result.notified_count == 1
        assert "New campaign:" in telegram.messages[0]
        assert "WT Campaign" in telegram.messages[0]
        assert "Live now" not in telegram.messages[0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_notifies_for_game_added_by_name():
    engine, factory = await _scan_session()

    async with factory() as session:
        user = await _seed_user(session, games=("War Thunder",))
        telegram = RecordingTelegram()

        result = await _run_scan(
            session, telegram, payload_data=warthunder_payload("ACTIVE")
        )

        assert result.notified_count == 1
        assert "New campaign:" in telegram.messages[0]
        assert "War Thunder" in telegram.messages[0]
        assert "Live now" not in telegram.messages[0]

        selected = await UserGameRepository(session).selected_names(user.id)
        assert selected == ["War Thunder"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_does_not_notify_untracked_game_start():
    engine, factory = await _scan_session()

    async with factory() as session:
        await _seed_user(session, games=("Rust",))
        payload_data = {
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

        result = await _run_scan(
            session, telegram, payload_data=payload_data
        )

        assert result.notified_count == 0
        assert telegram.messages == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_does_not_create_starts_when_the_bot_token_is_absent():
    engine, factory = await _scan_session()

    async with factory() as session:
        await _seed_user(session)
        telegram = FakeTelegram()  # configured = False

        result = await _run_scan(session, telegram)

        assert result.notified_count == 0
        starts = await session.scalar(
            select(func.count()).select_from(UserCampaignStart)
        )
        assert starts == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_retries_campaign_start_after_send_failure():
    engine, factory = await _scan_session()

    async with factory() as session:
        await _seed_user(session)
        telegram = FlakyTelegram()

        first = await _run_scan(session, telegram)
        assert first.notified_count == 0
        assert telegram.messages == []
        starts = await session.scalar(
            select(func.count()).select_from(UserCampaignStart)
        )
        assert starts == 1

        second = await _run_scan(session, telegram)
        assert second.notified_count == 1
        assert len(telegram.messages) == 1
        assert "New campaign:" in telegram.messages[0]
        starts = await session.scalar(
            select(func.count()).select_from(UserCampaignStart)
        )
        assert starts == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_creates_starts_only_for_opted_in_tracking_users():
    engine, factory = await _scan_session()

    async with factory() as session:
        opted_in = await _seed_user(
            session, twitch_user_id="1", login="opted-in"
        )
        opted_out = await _seed_user(
            session,
            twitch_user_id="2",
            login="opted-out",
            telegram_chat_id="222",
            telegram_enabled=False,
        )
        no_chat = await _seed_user(
            session,
            twitch_user_id="3",
            login="no-chat",
            telegram_chat_id="",
        )
        telegram = FlakyTelegram(failures=10)

        result = await _run_scan(session, telegram)

        # The opted-in user is the only one whose start is attempted (and it
        # stays pending because the send failed).
        assert result.notified_count == 0
        assert telegram.attempted_chat_ids == ["111"]

        rows = (await session.execute(select(UserCampaignStart))).scalars().all()
        assert {row.user_id for row in rows} == {opted_in.id}
        assert opted_out.id not in {row.user_id for row in rows}
        assert no_chat.id not in {row.user_id for row in rows}

    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_continues_after_one_users_telegram_fails():
    engine, factory = await _scan_session()

    async with factory() as session:
        first = await _seed_user(
            session,
            twitch_user_id="1",
            login="first",
            telegram_chat_id="111",
        )
        second = await _seed_user(
            session,
            twitch_user_id="2",
            login="second",
            telegram_chat_id="222",
        )
        telegram = FlakyTelegram(failures=1)

        result = await _run_scan(session, telegram)

        assert result.notified_count == 1
        assert telegram.chat_ids == ["222"]

        rows = (await session.execute(select(UserCampaignStart))).scalars().all()
        # The failed user keeps their pending start for the next scan.
        assert {row.user_id for row in rows} == {first.id}
        assert second.id not in {row.user_id for row in rows}

    await engine.dispose()
