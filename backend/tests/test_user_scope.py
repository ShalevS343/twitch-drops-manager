"""Per-user isolation and reconnect behaviour for personal repositories/services."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.exceptions import NotConfiguredError, ReconnectRequiredError
from app.domain.models import (
    Campaign,
    Game,
    Stream,
    StreamCampaignMatch,
    UserCampaignCompletion,
    UserDropProgress,
    UserNotification,
    UserWatchFocus,
)
from app.repositories.campaign_completions import CampaignCompletionRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.progress import ProgressRepository
from app.repositories.watch_focus import WatchFocusRepository
from app.services.progress_service import ProgressService
from app.services.watch_focus_service import WatchFocusService
from tests.support import connect_account, create_user, future, make_engine, past


class InventoryProvider:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error
        self.tokens: list[str] = []

    async def fetch_inventory(self, access_token):
        self.tokens.append(access_token)
        if self.error is not None:
            raise self.error
        return self.payload


class RecordingTelegram:
    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, message: str, chat_id: str) -> None:
        self.sent.append((chat_id, message))


def progress_row(drop_id: str, *, campaign_id: str = "campaign-1") -> dict:
    return {
        "drop_id": drop_id,
        "drop_name": drop_id,
        "campaign_gql_id": campaign_id,
        "campaign_name": "Test Campaign",
        "campaign_ends_at": "2099-12-01T00:00:00Z",
        "game_name": "Rust",
        "game_box_art_url": "",
        "required_minutes": 60,
        "current_minutes": 10,
        "is_claimed": False,
        "is_ready": False,
        "benefits": [],
    }


@pytest.mark.asyncio
async def test_progress_repository_isolates_rows_and_snapshots():
    engine, factory = await make_engine()

    async with factory() as session:
        first = await create_user(session, twitch_user_id="1", login="first")
        second = await create_user(session, twitch_user_id="2", login="second")
        await session.commit()

        await ProgressRepository(session, first.id).replace(
            [progress_row("first-drop")]
        )
        await ProgressRepository(session, second.id).replace(
            [progress_row("second-drop")]
        )
        await ProgressRepository(session, first.id).add_snapshots(
            [progress_row("first-drop")]
        )
        await ProgressRepository(session, second.id).add_snapshots(
            [progress_row("second-drop")]
        )
        await session.commit()

        first_rows = await ProgressRepository(session, first.id).list()
        second_rows = await ProgressRepository(session, second.id).list()
        assert [row.drop_id for row in first_rows] == ["first-drop"]
        assert [row.drop_id for row in second_rows] == ["second-drop"]

        first_snapshots = await ProgressRepository(session, first.id).snapshots_since(
            past(minutes=1)
        )
        assert {row.drop_id for row in first_snapshots} == {"first-drop"}

        # Replacing one user's inventory leaves the other user untouched.
        await ProgressRepository(session, first.id).replace(
            [progress_row("first-new")]
        )
        await session.commit()
        second_rows = await ProgressRepository(session, second.id).list()
        assert [row.drop_id for row in second_rows] == ["second-drop"]

        total = await session.scalar(select(func.count()).select_from(UserDropProgress))
        assert total == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_completions_and_notifications_are_scoped_per_user():
    engine, factory = await make_engine()

    async with factory() as session:
        first = await create_user(session, twitch_user_id="1", login="first")
        second = await create_user(session, twitch_user_id="2", login="second")
        await session.commit()

        await CampaignCompletionRepository(session, first.id).upsert_many(
            [
                {
                    "campaign_gql_id": "campaign-1",
                    "campaign_name": "One",
                    "game_name": "Rust",
                }
            ]
        )
        await NotificationRepository(session, first.id).claim("drop-ready:1")
        await session.commit()

        assert [
            row.campaign_gql_id
            for row in await CampaignCompletionRepository(session, second.id).list()
        ] == []
        assert await NotificationRepository(session, second.id).exists(
            "drop-ready:1"
        ) is False

        # Per-user dedupe: the same key can be claimed once for each user.
        assert await NotificationRepository(session, second.id).claim(
            "drop-ready:1"
        )
        await NotificationRepository(session, first.id).release("drop-ready:1")
        await session.commit()
        assert await NotificationRepository(session, first.id).exists(
            "drop-ready:1"
        ) is False
        assert await NotificationRepository(session, second.id).exists(
            "drop-ready:1"
        ) is True

        assert await session.scalar(
            select(func.count()).select_from(UserCampaignCompletion)
        ) == 1
        assert await session.scalar(
            select(func.count()).select_from(UserNotification)
        ) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_focus_repository_creates_one_row_per_user():
    engine, factory = await make_engine()

    async with factory() as session:
        first = await create_user(session, twitch_user_id="1", login="first")
        second = await create_user(session, twitch_user_id="2", login="second")
        await session.commit()

        first_row = await WatchFocusRepository(session, first.id).get_or_create()
        second_row = await WatchFocusRepository(session, second.id).get_or_create()
        await session.commit()

        assert first_row.id != second_row.id
        assert first_row.user_id == first.id
        assert second_row.user_id == second.id
        assert await WatchFocusRepository(session, first.id).get() is first_row
        assert await WatchFocusRepository(session, second.id).get() is second_row
        assert await session.scalar(
            select(func.count()).select_from(UserWatchFocus)
        ) == 2

    await engine.dispose()


async def _seed_focus_queue(session) -> None:
    game = Game(name="Rust")
    session.add(game)
    await session.flush()
    campaign = Campaign(
        external_id="Rust:campaign-1",
        game_id=game.id,
        name="Test Campaign",
        status="ACTIVE",
        ends_at="2099-12-01T00:00:00Z",
    )
    session.add(campaign)
    await session.flush()
    stream = Stream(
        user_login="alpha",
        user_name="Alpha",
        game_id=game.id,
        title="Alpha stream",
        viewers=10,
        language="en",
        url="https://www.twitch.tv/alpha",
        live=True,
    )
    session.add(stream)
    await session.flush()
    session.add(
        StreamCampaignMatch(
            stream_id=stream.id,
            campaign_id=campaign.id,
            eligibility="Potential campaign match; verify on Twitch",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_watch_focus_service_isolates_two_users():
    engine, factory = await make_engine()

    async with factory() as session:
        first = await create_user(session, twitch_user_id="1", login="first")
        second = await create_user(session, twitch_user_id="2", login="second")
        await session.commit()

        await _seed_focus_queue(session)
        # The second user sees only their own progress row.
        session.add(
            UserDropProgress(
                user_id=second.id,
                drop_id="second-drop",
                drop_name="second-drop",
                campaign_gql_id="campaign-1",
                campaign_name="Test Campaign",
                campaign_ends_at="2099-12-01T00:00:00Z",
                game_name="Rust",
                required_minutes=120,
                current_minutes=0,
            )
        )
        # Give the first user their own progress row (the shared seed row above
        # has no user).
        session.add(
            UserDropProgress(
                user_id=first.id,
                drop_id="first-drop",
                drop_name="first-drop",
                campaign_gql_id="campaign-1",
                campaign_name="Test Campaign",
                campaign_ends_at="2099-12-01T00:00:00Z",
                game_name="Rust",
                required_minutes=60,
                current_minutes=10,
            )
        )
        await session.commit()

        first_state = await WatchFocusService(session, first.id).set_enabled(True)
        second_state = await WatchFocusService(session, second.id).set_enabled(True)

        assert first_state.focus is not None
        assert second_state.focus is not None
        assert first_state.focus.target_minutes == 50
        assert second_state.focus.target_minutes == 120
        assert await session.scalar(
            select(func.count()).select_from(UserWatchFocus)
        ) == 2

    await engine.dispose()


async def _run_progress(session, user, provider, telegram=None):
    return await ProgressService(
        session,
        user.id,
        Settings(default_games="Rust", _env_file=None),
        provider,
        telegram or RecordingTelegram(),
    ).run()


@pytest.mark.asyncio
async def test_expired_token_marks_reconnect_and_success_clears_it():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="viewer")
        account = await connect_account(session, user, expires_at=past())
        await session.commit()

        with pytest.raises(ReconnectRequiredError):
            await _run_progress(session, user, InventoryProvider({}))

        await session.refresh(account)
        assert account.reconnect_required is True
        assert "reconnect" in account.last_error.lower()

        # A successful connection/sync clears the flag and records the time.
        account.access_token = "fresh-token"
        account.expires_at = future()
        account.reconnect_required = False
        await session.commit()

        result = await _run_progress(session, user, InventoryProvider({}))

        await session.refresh(account)
        assert result.connected is True
        assert account.reconnect_required is False
        assert account.last_error == ""
        assert account.last_synced_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_user_token_401_marks_reconnect_but_global_config_does_not():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="viewer")
        account = await connect_account(session, user, expires_at=future())
        await session.commit()

        with pytest.raises(ReconnectRequiredError):
            await _run_progress(
                session,
                user,
                InventoryProvider(error=ReconnectRequiredError("Twitch rejected token")),
            )
        await session.refresh(account)
        assert account.reconnect_required is True

        await session.refresh(account)
        account.reconnect_required = False
        account.last_error = ""
        await session.commit()

        with pytest.raises(NotConfiguredError):
            await _run_progress(
                session,
                user,
                InventoryProvider(
                    error=NotConfiguredError("Twitch client is not configured")
                ),
            )
        await session.refresh(account)
        assert account.reconnect_required is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_progress_service_skips_a_user_already_marked_reconnect_required():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="viewer")
        account = await connect_account(
            session,
            user,
            expires_at=future(),
            reconnect_required=True,
            last_error="reconnect",
        )
        await session.commit()
        provider = InventoryProvider({})

        result = await _run_progress(session, user, provider)

        assert result.connected is False
        assert provider.tokens == []
        await session.refresh(account)
        assert account.reconnect_required is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_telegram_opt_out_sends_nothing_and_uses_the_user_chat_id():
    engine, factory = await make_engine()

    payload = {
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
                        "self": {"isClaimed": False, "currentMinutesWatched": 60},
                    }
                ],
            }
        ]
    }

    async with factory() as session:
        opted_in = await create_user(
            session,
            twitch_user_id="1",
            login="opted-in",
            telegram_chat_id="111",
            telegram_enabled=True,
        )
        opted_out = await create_user(
            session,
            twitch_user_id="2",
            login="opted-out",
            telegram_chat_id="222",
            telegram_enabled=False,
        )
        await connect_account(session, opted_in, expires_at=future())
        await connect_account(session, opted_out, expires_at=future())
        await session.commit()

        telegram = RecordingTelegram()
        await _run_progress(
            session, opted_in, InventoryProvider(payload), telegram
        )
        await _run_progress(
            session, opted_out, InventoryProvider(payload), telegram
        )

        assert [chat_id for chat_id, _ in telegram.sent] == ["111"]

    await engine.dispose()
