from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.domain.models import (
    Campaign,
    DropProgress,
    Game,
    Stream,
    StreamCampaignMatch,
    WatchFocus,
)
from app.repositories.watch_focus import WatchFocusRepository
from app.services.watch_focus_service import WatchFocusError, WatchFocusService


class RecordingTelegram:
    configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, message: str) -> None:
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


async def _add_campaign(
    session, game: Game, external_id: str, name: str, ends_at: str | None
) -> Campaign:
    campaign = Campaign(
        external_id=external_id,
        game_id=game.id,
        name=name,
        status="ACTIVE",
        ends_at=ends_at,
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def _add_stream(
    session, game: Game, login: str, viewers: int, campaigns: list[Campaign]
) -> Stream:
    stream = Stream(
        user_login=login,
        user_name=login.title(),
        game_id=game.id,
        title=f"{login} stream",
        viewers=viewers,
        language="en",
        url=f"https://www.twitch.tv/{login}",
        live=True,
    )
    session.add(stream)
    await session.flush()

    for campaign in campaigns:
        session.add(
            StreamCampaignMatch(
                stream_id=stream.id,
                campaign_id=campaign.id,
                eligibility="Potential campaign match; verify on Twitch",
            )
        )
    await session.flush()
    return stream


def _progress(
    drop_id: str, campaign: Campaign, *, required: int, current: int
) -> DropProgress:
    return DropProgress(
        drop_id=drop_id,
        drop_name=drop_id,
        campaign_gql_id=campaign.external_id.rsplit(":", 1)[-1],
        campaign_name=campaign.name,
        campaign_ends_at=campaign.ends_at,
        game_name="Rust",
        required_minutes=required,
        current_minutes=current,
    )


async def _seed(session):
    game = Game(name="Rust", selected=True)
    session.add(game)
    await session.flush()

    early = await _add_campaign(
        session, game, "Rust:early", "Early Campaign", "2026-11-08T00:00:00Z"
    )
    late = await _add_campaign(
        session, game, "Rust:late", "Late Campaign", "2026-12-01T00:00:00Z"
    )

    early_stream = await _add_stream(session, game, "early-stream", 10, [early])
    late_low = await _add_stream(session, game, "late-low", 5, [late])
    late_high = await _add_stream(session, game, "late-high", 50, [late])

    session.add_all(
        [
            _progress("drop-early", early, required=20, current=10),
            _progress("drop-late", late, required=100, current=10),
        ]
    )
    await session.commit()
    return early, late, early_stream, late_low, late_high


@pytest.mark.asyncio
async def test_watch_focus_repository_keeps_a_single_row():
    engine, factory = await _session()

    async with factory() as session:
        repo = WatchFocusRepository(session)
        first = await repo.get_or_create()
        second = await repo.get_or_create()
        await session.commit()

        assert first.id == 1
        assert second.id == 1
        count = await session.scalar(select(func.count()).select_from(WatchFocus))
        assert count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_enable_focused_mode_dispatches_the_most_urgent_live():
    engine, factory = await _session()

    async with factory() as session:
        await _seed(session)

        state = await WatchFocusService(session).set_enabled(True)

        assert state.enabled is True
        assert state.status == "focused"
        assert state.max_watchers == 1
        assert state.focus is not None
        assert state.focus.user_login == "early-stream"
        assert state.focus.campaign_id == "early"
        assert state.focus.target_minutes == 10
        # The focused stream is not offered as a candidate again.
        assert "early-stream" not in {candidate.user_login for candidate in state.candidates}
        assert {candidate.user_login for candidate in state.candidates} == {
            "late-high",
            "late-low",
        }

        count = await session.scalar(select(func.count()).select_from(WatchFocus))
        assert count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_focus_replaces_the_single_watcher():
    engine, factory = await _session()

    async with factory() as session:
        _, _, _, late_low, _ = await _seed(session)
        service = WatchFocusService(session)

        await service.set_enabled(True)
        state = await service.focus(
            stream_id=late_low.id, campaign_id="late", strategy="manual"
        )

        assert state.focus is not None
        assert state.focus.user_login == "late-low"
        assert state.focus.campaign_id == "late"
        assert state.focus.reason == "manual"

        count = await session.scalar(select(func.count()).select_from(WatchFocus))
        assert count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_focus_rejects_a_stream_outside_the_queue():
    engine, factory = await _session()

    async with factory() as session:
        await _seed(session)

        with pytest.raises(WatchFocusError):
            await WatchFocusService(session).focus(
                stream_id=9999, campaign_id="early", strategy="manual"
            )

        # A rejected request does not leave a half-enabled watcher behind.
        assert await WatchFocusRepository(session).get() is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_notifies_and_keeps_focus_when_live_goes_offline():
    engine, factory = await _session()

    async with factory() as session:
        _, _, early_stream, _, _ = await _seed(session)
        telegram = RecordingTelegram()
        service = WatchFocusService(session, telegram=telegram)

        state = await service.set_enabled(True)
        assert state.focus is not None
        assert state.focus.user_login == "early-stream"

        # The next scan marks the focused channel offline.
        early_stream.live = False
        await session.commit()

        state = await service.reconcile()
        assert state.enabled is True
        assert state.status == "offline"
        assert state.focus is not None
        assert state.focus.user_login == "early-stream"
        assert state.focus.campaign_id == "early"
        assert state.focus.reason == "offline"
        # Another live for the same campaign is offered for a manual switch.
        assert {candidate.user_login for candidate in state.candidates} == {
            "late-high",
            "late-low",
        }
        assert len(telegram.messages) == 1
        assert "is no longer live" in telegram.messages[0]
        assert "Early Campaign" in telegram.messages[0]

        # Reconcile again: the offline notification is not repeated.
        again = await service.reconcile()
        assert again.status == "offline"
        assert len(telegram.messages) == 1

        count = await session.scalar(select(func.count()).select_from(WatchFocus))
        assert count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_keeps_focus_offline_when_no_live_is_left():
    engine, factory = await _session()

    async with factory() as session:
        await _seed(session)
        telegram = RecordingTelegram()
        service = WatchFocusService(session, telegram=telegram)
        await service.set_enabled(True)

        await session.execute(Stream.__table__.update().values(live=False))
        await session.commit()

        state = await service.reconcile()
        assert state.enabled is True
        assert state.status == "offline"
        assert state.focus is not None
        assert state.focus.campaign_id == "early"
        assert state.candidates == []
        assert len(telegram.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_turns_focus_off_when_campaign_completes():
    engine, factory = await _session()

    async with factory() as session:
        await _seed(session)
        telegram = RecordingTelegram()
        service = WatchFocusService(session, telegram=telegram)
        await service.set_enabled(True)

        # Claiming the last drop completes the focused campaign.
        await session.execute(
            DropProgress.__table__.update()
            .where(DropProgress.drop_id == "drop-early")
            .values(is_claimed=True, is_ready=False)
        )
        await session.commit()

        state = await service.reconcile()
        assert state.enabled is False
        assert state.status == "idle"
        assert state.reason == "completed"
        assert state.focus is None
        assert len(telegram.messages) == 1
        assert "campaign complete" in telegram.messages[0]
        assert "Focus mode has been turned off" in telegram.messages[0]

        # Completion is idempotent.
        again = await service.reconcile()
        assert again.enabled is False
        assert len(telegram.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_notifies_again_after_live_returns():
    engine, factory = await _session()

    async with factory() as session:
        _, _, early_stream, _, _ = await _seed(session)
        telegram = RecordingTelegram()
        service = WatchFocusService(session, telegram=telegram)
        await service.set_enabled(True)

        early_stream.live = False
        await session.commit()
        await service.reconcile()

        early_stream.live = True
        await session.commit()
        online = await service.reconcile()
        assert online.status == "focused"

        early_stream.live = False
        await session.commit()
        await service.reconcile()

        assert len(telegram.messages) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_next_moves_to_another_live_and_keeps_current_when_none_exists():
    engine, factory = await _session()

    async with factory() as session:
        await _seed(session)
        service = WatchFocusService(session)
        first = await service.set_enabled(True)
        assert first.focus is not None
        assert first.focus.user_login == "early-stream"

        moved = await service.focus(strategy="next")
        assert moved.focus is not None
        assert moved.focus.user_login == "late-high"
        assert moved.focus.reason == "next"

        # Only the current stream remains in the queue.
        await session.execute(
            Stream.__table__.update()
            .where(Stream.user_login != "late-high")
            .values(live=False)
        )
        await session.commit()

        stuck = await service.focus(strategy="next")
        assert stuck.focus is not None
        assert stuck.focus.user_login == "late-high"
        assert stuck.focus.reason == "next-unavailable"

    await engine.dispose()


@pytest.mark.asyncio
async def test_auto_can_target_a_specific_campaign():
    engine, factory = await _session()

    async with factory() as session:
        await _seed(session)
        service = WatchFocusService(session)

        state = await service.focus(campaign_id="late", strategy="auto")

        assert state.focus is not None
        assert state.focus.campaign_id == "late"
        assert state.focus.user_login == "late-high"

    await engine.dispose()


@pytest.mark.asyncio
async def test_disable_clears_the_focus_and_allows_reenable():
    engine, factory = await _session()

    async with factory() as session:
        await _seed(session)
        service = WatchFocusService(session)

        await service.set_enabled(True)
        stopped = await service.set_enabled(False)

        assert stopped.enabled is False
        assert stopped.status == "idle"
        assert stopped.focus is None

        restarted = await service.set_enabled(True)
        assert restarted.focus is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_watcher_waits_when_progress_has_no_open_drops():
    engine, factory = await _session()

    async with factory() as session:
        game = Game(name="Rust", selected=True)
        session.add(game)
        await session.flush()
        campaign = await _add_campaign(
            session, game, "Rust:early", "Early", "2026-11-08T00:00:00Z"
        )
        await _add_stream(session, game, "alpha", 100, [campaign])
        await session.commit()

        state = await WatchFocusService(session).set_enabled(True)

        assert state.enabled is True
        assert state.status == "waiting"
        assert state.focus is None
        assert state.candidates == []

    await engine.dispose()
