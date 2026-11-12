import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import migrations
from app.core.config import Settings
from app.core.db import Base
from app.core.migrations import run_multi_user_migration
from app.domain import models  # noqa: F401  (registers the tables on Base)

NEW_TABLE_NAMES = {
    "users",
    "user_sessions",
    "twitch_accounts",
    "user_games",
    "user_drop_progress",
    "user_progress_snapshots",
    "user_campaign_completions",
    "user_watch_focus",
    "user_notifications",
    "user_campaign_starts",
    "app_meta",
}

LEGACY_DDL = {
    "games": """
        CREATE TABLE games (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            box_art_url VARCHAR(512) NOT NULL DEFAULT '',
            twitch_game_id VARCHAR(64),
            selected BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """,
    "twitch_auth": """
        CREATE TABLE twitch_auth (
            id INTEGER PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL DEFAULT '',
            login VARCHAR(128) NOT NULL DEFAULT '',
            access_token TEXT NOT NULL DEFAULT '',
            refresh_token TEXT NOT NULL DEFAULT '',
            expires_at DATETIME,
            updated_at DATETIME NOT NULL
        )
    """,
    "twitch_profile": """
        CREATE TABLE twitch_profile (
            id INTEGER PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL DEFAULT '',
            display_name VARCHAR(255) NOT NULL DEFAULT '',
            profile_image_url VARCHAR(1024) NOT NULL DEFAULT '',
            connected_at DATETIME,
            updated_at DATETIME NOT NULL
        )
    """,
    "drop_progress": """
        CREATE TABLE drop_progress (
            id INTEGER PRIMARY KEY,
            drop_id VARCHAR(128) NOT NULL,
            drop_name VARCHAR(255) NOT NULL DEFAULT '',
            drop_instance_id VARCHAR(128),
            campaign_gql_id VARCHAR(128) NOT NULL DEFAULT '',
            campaign_name VARCHAR(512) NOT NULL DEFAULT '',
            campaign_ends_at VARCHAR(128),
            game_name VARCHAR(255) NOT NULL DEFAULT '',
            game_box_art_url VARCHAR(1024) NOT NULL DEFAULT '',
            starts_at VARCHAR(128),
            ends_at VARCHAR(128),
            required_minutes INTEGER NOT NULL DEFAULT 0,
            current_minutes INTEGER NOT NULL DEFAULT 0,
            is_claimed BOOLEAN NOT NULL DEFAULT 0,
            is_ready BOOLEAN NOT NULL DEFAULT 0,
            benefits JSON NOT NULL DEFAULT '[]',
            updated_at DATETIME NOT NULL
        )
    """,
    "progress_snapshots": """
        CREATE TABLE progress_snapshots (
            id INTEGER PRIMARY KEY,
            drop_id VARCHAR(128) NOT NULL,
            current_minutes INTEGER NOT NULL DEFAULT 0,
            recorded_at DATETIME NOT NULL
        )
    """,
    "campaign_completions": """
        CREATE TABLE campaign_completions (
            id INTEGER PRIMARY KEY,
            campaign_gql_id VARCHAR(128) NOT NULL,
            campaign_name VARCHAR(512) NOT NULL DEFAULT '',
            game_name VARCHAR(255) NOT NULL DEFAULT '',
            completed_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """,
    "watch_focus": """
        CREATE TABLE watch_focus (
            id INTEGER PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'idle',
            reason VARCHAR(64) NOT NULL DEFAULT '',
            stream_id INTEGER,
            user_login VARCHAR(128) NOT NULL DEFAULT '',
            user_name VARCHAR(255) NOT NULL DEFAULT '',
            stream_url VARCHAR(1024) NOT NULL DEFAULT '',
            stream_title TEXT NOT NULL DEFAULT '',
            game_name VARCHAR(255) NOT NULL DEFAULT '',
            game_box_art_url VARCHAR(1024) NOT NULL DEFAULT '',
            campaign_id VARCHAR(128) NOT NULL DEFAULT '',
            campaign_name VARCHAR(512) NOT NULL DEFAULT '',
            target_minutes INTEGER NOT NULL DEFAULT 0,
            ends_at VARCHAR(128),
            focused_at DATETIME,
            updated_at DATETIME NOT NULL
        )
    """,
    "notifications": """
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY,
            dedupe_key VARCHAR(512) NOT NULL,
            sent_at DATETIME NOT NULL
        )
    """,
    "campaign_starts": """
        CREATE TABLE campaign_starts (
            id INTEGER PRIMARY KEY,
            external_id VARCHAR(512) NOT NULL,
            detected_at DATETIME NOT NULL
        )
    """,
}


def _now_iso(offset: timedelta | None = None) -> str:
    value = datetime.now(timezone.utc) + (offset or timedelta())
    return value.isoformat()


async def _engine(*, legacy: bool = True):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        if legacy:
            for ddl in LEGACY_DDL.values():
                await connection.execute(text(ddl))
        new_tables = [
            table
            for name, table in Base.metadata.tables.items()
            if name in NEW_TABLE_NAMES
        ]
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection, tables=new_tables
            )
        )
    return engine


def _settings(monkeypatch, **overrides) -> Settings:
    values = {
        "_env_file": None,
        "owner_twitch_id": "",
        "telegram_chat_id": "",
        "registration_code": "",
        "registration_open": False,
    }
    values.update(overrides)
    settings = Settings(**values)
    monkeypatch.setattr(migrations, "get_settings", lambda: settings)
    return settings


async def _scalar(connection, sql: str, **params):
    result = await connection.execute(text(sql), params)
    return result.scalar_one_or_none()


async def _seed_legacy_owner(connection, *, expires_at: str) -> None:
    now = _now_iso()
    await connection.execute(
        text(
            "INSERT INTO twitch_auth (id, user_id, login, access_token, "
            "refresh_token, expires_at, updated_at) "
            "VALUES (1, '123', 'owner', 'legacy-token', '', :expires_at, :now)"
        ),
        {"expires_at": expires_at, "now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO twitch_profile (id, user_id, display_name, "
            "profile_image_url, connected_at, updated_at) "
            "VALUES (1, '123', 'Owner Display', 'https://example.test/owner.png', "
            ":now, :now)"
        ),
        {"now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO games (id, name, box_art_url, selected, created_at, "
            "updated_at) VALUES "
            "(1, 'Rust', '', 1, :now, :now), "
            "(2, 'Minecraft', '', 0, :now, :now), "
            "(3, 'Dota 2', '', 1, :now, :now)"
        ),
        {"now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO drop_progress (id, drop_id, drop_name, drop_instance_id, "
            "campaign_gql_id, campaign_name, campaign_ends_at, game_name, "
            "game_box_art_url, starts_at, ends_at, required_minutes, "
            "current_minutes, is_claimed, is_ready, benefits, updated_at) "
            "VALUES (1, 'drop-1', 'Drop One', 'instance-1', 'campaign-1', "
            "'Campaign One', NULL, 'Rust', '', NULL, NULL, 60, 30, 0, 1, "
            "'[\"Benefit\"]', :now)"
        ),
        {"now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO progress_snapshots (id, drop_id, current_minutes, "
            "recorded_at) VALUES (1, 'drop-1', 10, :now), "
            "(2, 'drop-1', 30, :now)"
        ),
        {"now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO campaign_completions (id, campaign_gql_id, "
            "campaign_name, game_name, completed_at, updated_at) "
            "VALUES (1, 'campaign-old', 'Old Campaign', 'Rust', :now, :now)"
        ),
        {"now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO watch_focus (id, enabled, status, reason, stream_id, "
            "user_login, user_name, stream_url, stream_title, game_name, "
            "game_box_art_url, campaign_id, campaign_name, target_minutes, "
            "ends_at, focused_at, updated_at) "
            "VALUES (1, 1, 'focused', 'manual', 7, 'streamer', 'Streamer', "
            "'https://twitch.tv/streamer', 'Title', 'Rust', '', 'campaign-1', "
            "'Campaign One', 60, NULL, :now, :now)"
        ),
        {"now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO notifications (id, dedupe_key, sent_at) VALUES "
            "(1, 'ready:drop-1', :now), (2, 'start:campaign-1', :now)"
        ),
        {"now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO campaign_starts (id, external_id, detected_at) "
            "VALUES (1, 'campaign-1', :now)"
        ),
        {"now": now},
    )


@pytest.mark.asyncio
async def test_migration_copies_legacy_owner_and_rows_once(monkeypatch):
    settings = _settings(monkeypatch, telegram_chat_id="555")
    engine = await _engine()
    expires_at = _now_iso(timedelta(days=1))

    async with engine.begin() as connection:
        await _seed_legacy_owner(connection, expires_at=expires_at)
        await run_multi_user_migration(connection)
        await run_multi_user_migration(connection)

        users = await connection.execute(text("SELECT * FROM users"))
        owners = users.mappings().all()
        assert len(owners) == 1
        owner = owners[0]
        assert owner["twitch_user_id"] == "123"
        assert owner["login"] == "owner"
        assert owner["display_name"] == "Owner Display"
        assert owner["profile_image_url"] == "https://example.test/owner.png"
        assert owner["role"] == "admin"
        assert owner["is_active"] in (1, True)
        assert owner["telegram_chat_id"] == settings.telegram_chat_id
        assert owner["telegram_enabled"] in (1, True)

        account = (
            await connection.execute(text("SELECT * FROM twitch_accounts"))
        ).mappings().one()
        assert account["user_id"] == owner["id"]
        assert account["access_token"] == "legacy-token"
        assert account["reconnect_required"] in (0, False)
        assert account["last_error"] == ""

        assert await _scalar(connection, "SELECT COUNT(*) FROM user_games") == 2
        assert (
            await _scalar(connection, "SELECT COUNT(*) FROM user_drop_progress")
            == 1
        )
        assert (
            await _scalar(connection, "SELECT COUNT(*) FROM user_progress_snapshots")
            == 2
        )
        assert (
            await _scalar(
                connection, "SELECT COUNT(*) FROM user_campaign_completions"
            )
            == 1
        )
        assert (
            await _scalar(connection, "SELECT COUNT(*) FROM user_watch_focus") == 1
        )
        assert (
            await _scalar(connection, "SELECT COUNT(*) FROM user_notifications")
            == 2
        )
        assert (
            await _scalar(connection, "SELECT COUNT(*) FROM user_campaign_starts")
            == 1
        )
        assert (
            await _scalar(
                connection,
                "SELECT value FROM app_meta WHERE key = 'multi_user_v1'",
            )
            == "done"
        )

        selected_games = await connection.execute(
            text(
                "SELECT g.name FROM user_games ug JOIN games g ON g.id = ug.game_id "
                "ORDER BY g.name"
            )
        )
        assert [row[0] for row in selected_games] == ["Dota 2", "Rust"]

        focus = (
            await connection.execute(text("SELECT * FROM user_watch_focus"))
        ).mappings().one()
        assert focus["enabled"] in (1, True)
        assert focus["campaign_id"] == "campaign-1"
        assert focus["user_id"] == owner["id"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_marks_expired_legacy_token_for_reconnect(monkeypatch):
    _settings(monkeypatch)
    engine = await _engine()
    expires_at = _now_iso(-timedelta(days=1))

    async with engine.begin() as connection:
        await _seed_legacy_owner(connection, expires_at=expires_at)
        await run_multi_user_migration(connection)
        account = (
            await connection.execute(text("SELECT * FROM twitch_accounts"))
        ).mappings().one()
        assert account["reconnect_required"] in (1, True)

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_creates_placeholder_admin_from_owner_setting(monkeypatch):
    _settings(monkeypatch, owner_twitch_id="999", telegram_chat_id="555")
    engine = await _engine(legacy=False)

    async with engine.begin() as connection:
        await run_multi_user_migration(connection)
        user = (
            await connection.execute(text("SELECT * FROM users"))
        ).mappings().one()
        assert user["twitch_user_id"] == "999"
        assert user["role"] == "admin"
        assert user["telegram_chat_id"] == "555"
        assert user["telegram_enabled"] in (1, True)
        assert (
            await _scalar(connection, "SELECT COUNT(*) FROM twitch_accounts") == 0
        )
        assert (
            await _scalar(
                connection,
                "SELECT COUNT(*) FROM app_meta "
                "WHERE key = 'first_admin_claimed'",
            )
            == 1
        )
        assert (
            await _scalar(
                connection,
                "SELECT value FROM app_meta WHERE key = 'multi_user_v1'",
            )
            == "done"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_without_token_or_owner_setting_creates_no_user(monkeypatch):
    _settings(monkeypatch)
    engine = await _engine(legacy=False)

    async with engine.begin() as connection:
        await run_multi_user_migration(connection)
        assert await _scalar(connection, "SELECT COUNT(*) FROM users") == 0
        assert (
            await _scalar(
                connection,
                "SELECT value FROM app_meta WHERE key = 'multi_user_v1'",
            )
            == "done"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_aborts_on_empty_legacy_user_id(monkeypatch):
    _settings(monkeypatch)
    engine = await _engine()

    async with engine.begin() as connection:
        now = _now_iso()
        await connection.execute(
            text(
                "INSERT INTO twitch_auth (id, user_id, login, access_token, "
                "refresh_token, expires_at, updated_at) "
                "VALUES (1, '', 'owner', 'legacy-token', '', NULL, :now)"
            ),
            {"now": now},
        )

    with pytest.raises(RuntimeError, match="OWNER_TWITCH_ID"):
        async with engine.begin() as connection:
            await run_multi_user_migration(connection)

    # The failed transaction rolled the migration flag and all copies back.
    async with engine.connect() as connection:
        assert (
            await _scalar(
                connection,
                "SELECT COUNT(*) FROM app_meta WHERE key = 'multi_user_v1'",
            )
            == 0
        )
        assert await _scalar(connection, "SELECT COUNT(*) FROM users") == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_aborts_when_existing_users_conflict(monkeypatch):
    _settings(monkeypatch)
    engine = await _engine()

    async with engine.begin() as connection:
        now = _now_iso()
        await connection.execute(
            text(
                "INSERT INTO users (id, twitch_user_id, login, display_name, "
                "profile_image_url, role, is_active, telegram_chat_id, "
                "telegram_enabled, created_at, updated_at) "
                "VALUES (1, 'other', 'other', '', '', 'admin', 1, '', 0, :now, :now)"
            ),
            {"now": now},
        )
        await connection.execute(
            text(
                "INSERT INTO twitch_auth (id, user_id, login, access_token, "
                "refresh_token, expires_at, updated_at) "
                "VALUES (1, '123', 'owner', 'legacy-token', '', NULL, :now)"
            ),
            {"now": now},
        )

    with pytest.raises(RuntimeError, match="twitch_user_id"):
        async with engine.begin() as connection:
            await run_multi_user_migration(connection)

    async with engine.connect() as connection:
        assert (
            await _scalar(
                connection,
                "SELECT COUNT(*) FROM app_meta WHERE key = 'multi_user_v1'",
            )
            == 0
        )
        assert await _scalar(connection, "SELECT COUNT(*) FROM users") == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_startup_runs_the_migration_once(monkeypatch, tmp_path):
    _settings(monkeypatch, telegram_chat_id="555")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'drops.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        for ddl in LEGACY_DDL.values():
            await connection.execute(text(ddl))
        new_tables = [
            table
            for name, table in Base.metadata.tables.items()
            if name in NEW_TABLE_NAMES
        ]
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection, tables=new_tables
            )
        )
        await _seed_legacy_owner(
            connection, expires_at=_now_iso(timedelta(days=1))
        )

    async def migrate():
        async with engine.begin() as connection:
            await run_multi_user_migration(connection)

    await asyncio.gather(migrate(), migrate())

    async with engine.connect() as connection:
        assert await _scalar(connection, "SELECT COUNT(*) FROM users") == 1
        assert await _scalar(connection, "SELECT COUNT(*) FROM user_games") == 2
        assert await _scalar(connection, "SELECT COUNT(*) FROM user_notifications") == 2
        assert (
            await _scalar(
                connection,
                "SELECT COUNT(*) FROM app_meta WHERE key = 'multi_user_v1' "
                "AND value = 'done'",
            )
            == 1
        )
        assert (
            await _scalar(
                connection,
                "SELECT COUNT(*) FROM app_meta "
                "WHERE key = 'first_admin_claimed'",
            )
            == 1
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_ignores_a_profile_for_another_twitch_user(monkeypatch):
    _settings(monkeypatch)
    engine = await _engine()
    now = _now_iso()

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO twitch_auth (id, user_id, login, access_token, "
                "refresh_token, expires_at, updated_at) "
                "VALUES (1, '123', 'owner', 'legacy-token', '', NULL, :now)"
            ),
            {"now": now},
        )
        await connection.execute(
            text(
                "INSERT INTO twitch_profile (id, user_id, display_name, "
                "profile_image_url, connected_at, updated_at) "
                "VALUES (1, 'other', 'Wrong Person', 'https://example.test/wrong.png', "
                ":now, :now)"
            ),
            {"now": now},
        )
        await run_multi_user_migration(connection)

        user = (
            await connection.execute(text("SELECT * FROM users"))
        ).mappings().one()
        assert user["display_name"] == "owner"
        assert user["profile_image_url"] == ""

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_retries_when_the_flag_is_not_done(monkeypatch):
    _settings(monkeypatch)
    engine = await _engine()
    expires_at = _now_iso(timedelta(days=1))

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) "
                "VALUES ('multi_user_v1', 'pending', :now)"
            ),
            {"now": _now_iso()},
        )
        await _seed_legacy_owner(connection, expires_at=expires_at)
        await run_multi_user_migration(connection)

        assert await _scalar(connection, "SELECT COUNT(*) FROM users") == 1
        assert (
            await _scalar(
                connection,
                "SELECT value FROM app_meta WHERE key = 'multi_user_v1'",
            )
            == "done"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_does_not_autocreate_owner_when_users_exist(monkeypatch):
    _settings(monkeypatch, owner_twitch_id="999")
    engine = await _engine(legacy=False)

    async with engine.begin() as connection:
        now = _now_iso()
        await connection.execute(
            text(
                "INSERT INTO users (id, twitch_user_id, login, display_name, "
                "profile_image_url, role, is_active, telegram_chat_id, "
                "telegram_enabled, created_at, updated_at) "
                "VALUES (1, 'existing', 'existing', '', '', 'admin', 1, '', 0, "
                ":now, :now)"
            ),
            {"now": now},
        )
        await run_multi_user_migration(connection)
        assert await _scalar(connection, "SELECT COUNT(*) FROM users") == 1
        assert (
            await _scalar(
                connection,
                "SELECT twitch_user_id FROM users WHERE id = 1",
            )
            == "existing"
        )

    await engine.dispose()
