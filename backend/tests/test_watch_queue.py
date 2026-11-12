from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.watch_queue import list_watch_queue
from app.core.db import Base
from app.domain.models import (
    Campaign,
    Game,
    Stream,
    StreamCampaignMatch,
    UserDropProgress,
    UserProgressSnapshot,
)
from tests.support import create_user


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
    session, game: Game, login: str, viewers: int, campaigns: list[Campaign], live: bool = True
) -> Stream:
    stream = Stream(
        user_login=login,
        user_name=login.title(),
        game_id=game.id,
        title=f"{login} stream",
        viewers=viewers,
        language="en",
        url=f"https://www.twitch.tv/{login}",
        live=live,
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
    user_id: int,
    drop_id: str,
    campaign: Campaign,
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
        campaign_gql_id=campaign.external_id.rsplit(":", 1)[-1],
        campaign_name=campaign.name,
        campaign_ends_at=campaign.ends_at,
        game_name="Rust",
        required_minutes=required,
        current_minutes=current,
        is_claimed=claimed,
        is_ready=required > 0 and current >= required and not claimed,
    )


@pytest.mark.asyncio
async def test_watch_queue_filters_in_progress_and_selects_next_drop():
    engine, factory = await _session()

    async with factory() as session:
        game = Game(name="Rust")
        session.add(game)
        await session.flush()
        user = await create_user(session, twitch_user_id="1", login="one")

        in_progress = await _add_campaign(
            session, game, "Rust:campaign-1", "Campaign One", "2026-11-10T00:00:00Z"
        )
        other = await _add_campaign(
            session, game, "Rust:campaign-2", "Campaign Two", "2026-11-09T00:00:00Z"
        )
        ready = await _add_campaign(
            session, game, "Rust:campaign-3", "Campaign Three", "2026-11-11T00:00:00Z"
        )

        await _add_stream(session, game, "alpha", 100, [in_progress])
        await _add_stream(session, game, "beta", 200, [other])
        await _add_stream(session, game, "delta", 50, [ready])
        await _add_stream(session, game, "offline", 999, [in_progress], live=False)

        session.add_all(
            [
                _progress(user.id, "drop-1", in_progress, required=100, current=40),
                _progress(user.id, "drop-2", in_progress, required=40, current=10),
                _progress(user.id, "drop-claimed", in_progress, required=30, current=30, claimed=True),
                _progress(user.id, "drop-ready", ready, required=30, current=30),
            ]
        )
        await session.commit()

        items = await list_watch_queue(session, user)

        logins = [item.user_login for item in items]
        assert "beta" not in logins
        assert "offline" not in logins

        alpha = next(item for item in items if item.user_login == "alpha")
        assert alpha.game_name == "Rust"
        assert alpha.viewers == 100
        assert len(alpha.campaigns) == 1
        assert alpha.campaigns[0].campaign_id == "campaign-1"
        assert alpha.campaigns[0].campaign_name == "Campaign One"
        # 60 remaining on drop-1 and 30 on drop-2 share watch time: max = 60.
        assert alpha.campaigns[0].remaining_minutes == 60
        assert alpha.campaigns[0].next_drop_name == "drop-2"
        assert alpha.campaigns[0].next_drop_remaining_minutes == 30

        # When every unclaimed drop is already complete, the first unclaimed
        # drop is still reported as the next one.
        delta = next(item for item in items if item.user_login == "delta")
        assert delta.campaigns[0].next_drop_name == "drop-ready"
        assert delta.campaigns[0].next_drop_remaining_minutes == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_queue_sorts_by_earliest_end_remaining_and_viewers():
    engine, factory = await _session()

    async with factory() as session:
        game = Game(name="Rust")
        session.add(game)
        await session.flush()
        user = await create_user(session, twitch_user_id="1", login="one")

        early = await _add_campaign(
            session, game, "Rust:early", "Early", "2026-11-08T00:00:00Z"
        )
        late = await _add_campaign(
            session, game, "Rust:late", "Late", "2026-12-01T00:00:00Z"
        )
        unknown = await _add_campaign(session, game, "Rust:unknown", "Unknown", None)

        await _add_stream(session, game, "early-stream", 1, [early])
        await _add_stream(session, game, "late-low", 10, [late])
        await _add_stream(session, game, "late-high", 20, [late])
        await _add_stream(session, game, "unknown-stream", 999, [unknown])

        session.add_all(
            [
                _progress(user.id, "drop-early", early, required=20, current=10),
                _progress(user.id, "drop-late", late, required=200, current=100),
                _progress(user.id, "drop-unknown", unknown, required=100, current=50),
            ]
        )
        await session.commit()

        items = await list_watch_queue(session, user)

        assert [item.user_login for item in items] == [
            "early-stream",
            "late-high",
            "late-low",
            "unknown-stream",
        ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_queue_uses_a_single_flat_join_and_three_queries():
    engine, factory = await _session()

    async with factory() as session:
        game = Game(name="Rust")
        session.add(game)
        await session.flush()
        user = await create_user(session, twitch_user_id="1", login="one")

        campaign = await _add_campaign(
            session, game, "Rust:campaign-1", "Campaign One", "2026-11-10T00:00:00Z"
        )
        await _add_stream(session, game, "alpha", 100, [campaign])
        session.add(_progress(user.id, "drop-1", campaign, required=100, current=40))
        await session.commit()

        statements: list[str] = []

        def record_statement(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
        items = await list_watch_queue(session, user)
        event.remove(engine.sync_engine, "before_cursor_execute", record_statement)

        assert len(items) == 1
        assert len(statements) == 3
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_queue_falls_back_to_flat_campaign_name_and_ends_at():
    engine, factory = await _session()

    async with factory() as session:
        game = Game(name="Rust")
        session.add(game)
        await session.flush()
        user = await create_user(session, twitch_user_id="1", login="one")

        campaign = await _add_campaign(
            session, game, "Rust:campaign-1", "Campaign One", "2026-11-10T00:00:00Z"
        )
        await _add_stream(session, game, "alpha", 100, [campaign])
        session.add(
            UserDropProgress(
                user_id=user.id,
                drop_id="drop-1",
                drop_name="Drop One",
                campaign_gql_id="campaign-1",
                campaign_name="",
                campaign_ends_at=None,
                game_name="Rust",
                required_minutes=100,
                current_minutes=40,
            )
        )
        await session.commit()

        items = await list_watch_queue(session, user)

        assert len(items) == 1
        assert items[0].campaigns[0].campaign_name == "Campaign One"
        assert items[0].campaigns[0].ends_at == "2026-11-10T00:00:00Z"

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_queue_reports_campaign_remaining_minutes():
    engine, factory = await _session()

    async with factory() as session:
        game = Game(name="Rust")
        session.add(game)
        await session.flush()
        user = await create_user(session, twitch_user_id="1", login="one")

        campaign = await _add_campaign(
            session, game, "Rust:campaign-1", "Campaign One", "2026-11-10T00:00:00Z"
        )
        await _add_stream(session, game, "alpha", 100, [campaign])
        session.add(_progress(user.id, "drop-1", campaign, required=120, current=60))

        now = datetime.now(timezone.utc)
        session.add_all(
            [
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-1",
                    current_minutes=30,
                    recorded_at=now - timedelta(minutes=60),
                ),
                UserProgressSnapshot(
                    user_id=user.id,
                    drop_id="drop-1", current_minutes=60, recorded_at=now
                ),
            ]
        )
        await session.commit()

        items = await list_watch_queue(session, user)

        assert len(items) == 1
        assert items[0].campaigns[0].remaining_minutes == 60

    await engine.dispose()
