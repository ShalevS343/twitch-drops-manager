from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.streams import list_streams
from app.core.db import Base
from app.domain.models import (
    Campaign,
    CampaignCompletion,
    Game,
    Stream,
    StreamCampaignMatch,
)


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


async def _add_campaign(session, game: Game, external_id: str, name: str) -> Campaign:
    campaign = Campaign(
        external_id=external_id,
        game_id=game.id,
        name=name,
        status="ACTIVE",
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def _add_stream(
    session,
    game: Game,
    login: str,
    viewers: int,
    campaigns: list[Campaign],
    live: bool = True,
) -> Stream:
    stream = Stream(
        user_login=login,
        user_name=login.title(),
        game_id=game.id,
        title=f"{login} stream",
        viewers=viewers,
        language="en",
        started_at="2026-01-01T00:00:00Z",
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


@pytest.mark.asyncio
async def test_streams_preserves_contract_and_hides_unmatched_streams():
    engine, factory = await _session()

    async with factory() as session:
        rust = Game(
            name="Rust",
            box_art_url="https://example.test/rust.jpg",
            twitch_game_id="263490",
            selected=True,
        )
        session.add(rust)
        await session.flush()
        campaign = await _add_campaign(session, rust, "Rust:campaign-1", "Rust Drops")

        await _add_stream(session, rust, "alpha", 100, [campaign])
        await _add_stream(session, rust, "beta", 50, [])
        await _add_stream(session, rust, "offline", 999, [campaign], live=False)
        await session.commit()

        statements: list[str] = []

        def record_statement(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
        streams = await list_streams(session, game=None, live=True)
        event.remove(engine.sync_engine, "before_cursor_execute", record_statement)

        # One flat stream query plus one query for completed campaign ids.
        assert len(statements) == 2
        # beta has no matching campaign, so it does not advance any drops.
        assert [stream.user_login for stream in streams] == ["alpha"]

        alpha = streams[0]
        assert alpha.id is not None
        assert alpha.user_name == "Alpha"
        assert alpha.title == "alpha stream"
        assert alpha.viewers == 100
        assert alpha.language == "en"
        assert alpha.started_at == "2026-01-01T00:00:00Z"
        assert alpha.url == "https://www.twitch.tv/alpha"
        assert alpha.live is True
        assert alpha.game.id == rust.id
        assert alpha.game.name == "Rust"
        assert alpha.game.box_art_url == "https://example.test/rust.jpg"
        assert alpha.game.twitch_game_id == "263490"
        assert alpha.game.selected is True
        assert alpha.game.campaign_count == 0
        assert alpha.matching_campaigns == ["Rust Drops"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_streams_preserves_game_and_live_filters():
    engine, factory = await _session()

    async with factory() as session:
        rust = Game(name="Rust", selected=True)
        other = Game(name="Minecraft", selected=True)
        session.add_all([rust, other])
        await session.flush()

        campaign = await _add_campaign(session, rust, "Rust:campaign-1", "Rust Drops")
        await _add_stream(session, rust, "rust-live", 10, [campaign])
        await _add_stream(session, rust, "rust-offline", 20, [campaign], live=False)
        await _add_stream(session, other, "minecraft-live", 30, [])
        await session.commit()

        rust_streams = await list_streams(session, game="rust", live=None)
        assert [stream.user_login for stream in rust_streams] == [
            "rust-offline",
            "rust-live",
        ]

        live_streams = await list_streams(session, game=None, live=True)
        # minecraft-live has no campaign match, so it advances nothing.
        assert [stream.user_login for stream in live_streams] == ["rust-live"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_streams_only_returns_uncompleted_campaigns():
    engine, factory = await _session()

    async with factory() as session:
        rust = Game(name="Rust", selected=True)
        session.add(rust)
        await session.flush()

        completed = await _add_campaign(
            session, rust, "Rust:completed-1", "Completed Drops"
        )
        open_campaign = await _add_campaign(
            session, rust, "Rust:open-1", "Open Drops"
        )

        await _add_stream(session, rust, "only-completed", 300, [completed])
        await _add_stream(
            session, rust, "mixed", 200, [completed, open_campaign]
        )
        await _add_stream(session, rust, "only-open", 100, [open_campaign])

        session.add(
            CampaignCompletion(
                campaign_gql_id="completed-1",
                campaign_name="Completed Drops",
                game_name="Rust",
            )
        )
        await session.commit()

        streams = await list_streams(session, game=None, live=True)

        assert [stream.user_login for stream in streams] == ["mixed", "only-open"]
        assert streams[0].matching_campaigns == ["Open Drops"]
        assert streams[1].matching_campaigns == ["Open Drops"]

    await engine.dispose()
