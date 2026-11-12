from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.api.v1.campaigns import list_campaigns
from app.api.v1.progress import list_progress
from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.domain.models import (
    Campaign,
    Reward,
    UserCampaignCompletion,
    UserDropProgress,
    UserNotification,
    UserProgressSnapshot,
)
from app.services.progress_service import ProgressService
from tests.support import (
    connect_account,
    create_user,
    future,
    make_engine,
)


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


class CompletedProvider:
    def __init__(self, claimed_rewards: int) -> None:
        self.claimed_rewards = claimed_rewards

    async def fetch_inventory(self, access_token):
        return {
            "dropCampaignsInProgress": [],
            "earnedDropRewards": {
                "edges": [
                    {
                        "node": {
                            "id": f"item-{index}",
                            "status": "CLAIMED",
                            "item": {"id": f"item-{index}"},
                            "campaign": {"id": "campaign-1"},
                        }
                    }
                    for index in range(self.claimed_rewards)
                ]
            },
        }

    async def refresh(self, refresh_token):
        raise AssertionError("Token should not need refreshing in this test")


class FakeTelegram:
    configured = True

    def __init__(self):
        self.messages = []
        self.chat_ids = []

    async def send(self, message, chat_id):
        self.messages.append(message)
        self.chat_ids.append(chat_id)


async def _connected_user(
    session, *, twitch_user_id: str = "123", login: str = "viewer"
):
    user = await create_user(
        session,
        twitch_user_id=twitch_user_id,
        login=login,
        telegram_chat_id="111",
        telegram_enabled=True,
    )
    await connect_account(session, user, expires_at=future())
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_progress_sync_persists_drops_and_notifies_once():
    engine, factory = await make_engine()
    telegram = FakeTelegram()

    async with factory() as session:
        user = await _connected_user(session)

        service = ProgressService(
            session,
            user.id,
            Settings(default_games="Rust", _env_file=None),
            FakeProvider(),
            telegram,
        )

        first = await service.run()
        assert first.connected is True
        assert first.campaign_count == 1
        assert first.drop_count == 2
        assert first.notified_count == 1
        assert len(telegram.messages) == 1
        assert telegram.chat_ids == ["111"]
        assert "First Drop" in telegram.messages[0]
        assert "https://www.twitch.tv/drops/inventory" in telegram.messages[0]

        total = await session.scalar(
            select(func.count()).select_from(UserDropProgress)
        )
        assert total == 2
        ready = await session.scalar(
            select(func.count()).select_from(UserDropProgress).where(
                UserDropProgress.is_ready.is_(True)
            )
        )
        assert ready == 1

        # A second sync must not re-send the same "ready to claim" message.
        second = await service.run()
        assert second.notified_count == 0
        assert len(telegram.messages) == 1

        notification_total = await session.scalar(
            select(func.count()).select_from(UserNotification)
        )
        assert notification_total == 1

    await engine.dispose()


async def _seed_catalog_campaign(session, user_id: int) -> Campaign:
    from app.domain.models import Game, UserGame

    game = Game(name="Rust")
    session.add(game)
    await session.flush()
    session.add(UserGame(user_id=user_id, game_id=game.id))

    campaign = Campaign(
        external_id="Rust:campaign-1",
        game_id=game.id,
        name="Completed Campaign",
        status="ACTIVE",
        ends_at="2026-12-01T00:00:00Z",
    )
    session.add(campaign)
    await session.flush()
    session.add_all(
        [
            Reward(
                campaign_id=campaign.id,
                name="Drop One",
                benefit_name="Skin",
                required_minutes=60,
            ),
            Reward(
                campaign_id=campaign.id,
                name="Drop Two",
                benefit_name="Booster",
                required_minutes=120,
            ),
        ]
    )
    await session.commit()
    return campaign


async def _run_completed_progress(session, claimed_rewards: int):
    user = await _connected_user(session)
    await _seed_catalog_campaign(session, user.id)
    result = await ProgressService(
        session,
        user.id,
        Settings(default_games="Rust", _env_file=None),
        CompletedProvider(claimed_rewards),
        FakeTelegram(),
    ).run()
    return result, user


@pytest.mark.asyncio
async def test_progress_records_campaign_completion_from_earned_rewards():
    engine, factory = await make_engine()

    async with factory() as session:
        _, user = await _run_completed_progress(session, claimed_rewards=2)

        completion_count = await session.scalar(
            select(func.count()).select_from(UserCampaignCompletion)
        )
        assert completion_count == 1

        campaigns = await list_campaigns(
            session, user, game=None, status=None, active_only=False
        )
        assert len(campaigns) == 1
        assert campaigns[0].completed is True

        progress = await list_progress(session, user)
        assert len(progress) == 1
        completed = progress[0]
        assert completed.campaign_name == "Completed Campaign"
        assert completed.claimed_count == 2
        assert completed.total_count == 2
        assert completed.remaining_minutes == 0
        assert all(drop.is_claimed for drop in completed.drops)
        assert all(drop.remaining_minutes == 0 for drop in completed.drops)

    await engine.dispose()


@pytest.mark.asyncio
async def test_progress_does_not_complete_a_campaign_with_missing_rewards():
    engine, factory = await make_engine()

    async with factory() as session:
        _, user = await _run_completed_progress(session, claimed_rewards=1)

        completion_count = await session.scalar(
            select(func.count()).select_from(UserCampaignCompletion)
        )
        assert completion_count == 0

        campaigns = await list_campaigns(
            session, user, game=None, status=None, active_only=False
        )
        assert campaigns[0].completed is False
        assert await list_progress(session, user) == []

    await engine.dispose()


def _drop_row(
    user_id: int,
    drop_id: str,
    *,
    required: int,
    current: int,
    claimed: bool = False,
    drop_name: str | None = None,
) -> UserDropProgress:
    return UserDropProgress(
        user_id=user_id,
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
async def test_progress_api_computes_rate_from_snapshots():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                _drop_row(user.id, "drop-fast", required=120, current=60),
                _drop_row(user.id, "drop-quick", required=60, current=30),
                _drop_row(user.id, "drop-claimed", required=30, current=30, claimed=True),
            ]
        )
        session.add_all(
            [
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-fast",
                    current_minutes=30,
                    recorded_at=now - timedelta(minutes=60),
                ),
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-fast",
                    current_minutes=60,
                    recorded_at=now,
                ),
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-quick",
                    current_minutes=0,
                    recorded_at=now - timedelta(minutes=60),
                ),
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-quick",
                    current_minutes=60,
                    recorded_at=now,
                ),
            ]
        )
        await session.commit()

        campaigns = await list_progress(session, user)

        assert len(campaigns) == 1
        campaign = campaigns[0]
        # Drop requirements share watch time: max(60, 30) = 60, not 90.
        assert campaign.remaining_minutes == 60

        drops = {drop.drop_id: drop for drop in campaign.drops}
        assert drops["drop-fast"].remaining_minutes == 60
        assert drops["drop-fast"].rate_minutes_per_hour == pytest.approx(30.0)

        assert drops["drop-quick"].remaining_minutes == 30
        assert drops["drop-quick"].rate_minutes_per_hour == pytest.approx(60.0)

        assert drops["drop-claimed"].remaining_minutes == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_campaign_remaining_minutes_uses_the_largest_drop_not_the_sum():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        session.add_all(
            [
                _drop_row(user.id, "drop-1h", required=60, current=0),
                _drop_row(user.id, "drop-2h", required=120, current=0),
            ]
        )
        await session.commit()

        campaigns = await list_progress(session, user)

        assert len(campaigns) == 1
        # Finishing both drops takes 2h, not 1h + 2h.
        assert campaigns[0].remaining_minutes == 120

    await engine.dispose()


@pytest.mark.asyncio
async def test_progress_api_ignores_slow_watch_rate():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        now = datetime.now(timezone.utc)
        session.add(_drop_row(user.id, "drop-slow", required=60, current=30))
        session.add_all(
            [
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-slow",
                    current_minutes=30,
                    recorded_at=now - timedelta(minutes=60),
                ),
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-slow",
                    current_minutes=30,
                    recorded_at=now,
                ),
            ]
        )
        await session.commit()

        campaigns = await list_progress(session, user)

        drop = campaigns[0].drops[0]
        assert drop.remaining_minutes == 30
        assert drop.rate_minutes_per_hour is None

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
    engine, factory = await make_engine()
    telegram = FakeTelegram()

    async with factory() as session:
        user = await _connected_user(session)

        end_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        service = ProgressService(
            session,
            user.id,
            Settings(default_games="Rust", _env_file=None),
            DeadlineProvider(end_at),
            telegram,
        )

        first = await service.run()
        assert first.notified_count == 1
        assert len(telegram.messages) == 1
        assert "Test Campaign" in telegram.messages[0]
        assert "ends in ~2h" in telegram.messages[0]
        assert "1 drops left (60 min)" in telegram.messages[0]

        snapshot_total = await session.scalar(
            select(func.count()).select_from(UserProgressSnapshot)
        )
        assert snapshot_total == 1

        keys = set(
            (
                await session.execute(select(UserNotification.dedupe_key))
            ).scalars().all()
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
    engine, factory = await make_engine()
    telegram = FakeTelegram()

    async with factory() as session:
        user = await _connected_user(session)

        service = ProgressService(
            session,
            user.id,
            Settings(default_games="Rust", _env_file=None),
            TwoReadyDropsProvider(),
            telegram,
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
            (
                await session.execute(select(UserNotification.dedupe_key))
            ).scalars().all()
        )
        assert keys == {"drop-ready:drop-1", "drop-ready:drop-2"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_progress_service_uses_24h_window_when_campaign_ends_in_10h():
    engine, factory = await make_engine()
    telegram = FakeTelegram()

    async with factory() as session:
        user = await _connected_user(session)

        end_at = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
        service = ProgressService(
            session,
            user.id,
            Settings(default_games="Rust", _env_file=None),
            DeadlineProvider(end_at),
            telegram,
        )

        result = await service.run()
        assert result.notified_count == 1
        assert len(telegram.messages) == 1
        assert "ends in ~24h" in telegram.messages[0]

        keys = set(
            (
                await session.execute(select(UserNotification.dedupe_key))
            ).scalars().all()
        )
        assert keys == {"campaign-ending:campaign-1:24h"}

    await engine.dispose()


class FlakyTelegram:
    configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.failures = 1

    async def send(self, message, chat_id):
        if self.failures:
            self.failures -= 1
            raise ProviderError("telegram unavailable")
        self.messages.append(message)


@pytest.mark.asyncio
async def test_progress_service_releases_claim_when_send_fails():
    engine, factory = await make_engine()
    telegram = FlakyTelegram()

    async with factory() as session:
        user = await _connected_user(session)

        end_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        service = ProgressService(
            session,
            user.id,
            Settings(default_games="Rust", _env_file=None),
            DeadlineProvider(end_at),
            telegram,
        )

        first = await service.run()
        assert first.notified_count == 0
        assert telegram.messages == []
        notification_total = await session.scalar(
            select(func.count()).select_from(UserNotification)
        )
        assert notification_total == 0

        second = await service.run()
        assert second.notified_count == 1
        assert len(telegram.messages) == 1
        assert "ends in ~2h" in telegram.messages[0]

    await engine.dispose()
