"""Idempotent schema migrations for the device-code login."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import db
from app.core.db import Base
from app.core.migrations import (
    SCHEMA_MIGRATION_KEY,
    run_schema_migrations,
)
from app.domain import models  # noqa: F401  (registers tables on Base)

LEGACY_TWITCH_ACCOUNTS_DDL = """
    CREATE TABLE twitch_accounts (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL UNIQUE,
        access_token TEXT NOT NULL DEFAULT '',
        expires_at DATETIME,
        connected_at DATETIME NOT NULL,
        last_synced_at DATETIME,
        last_error TEXT NOT NULL DEFAULT '',
        reconnect_required BOOLEAN NOT NULL DEFAULT 0
    )
"""

APP_META_DDL = """
    CREATE TABLE app_meta (
        key VARCHAR(64) PRIMARY KEY,
        value VARCHAR(255) NOT NULL DEFAULT '',
        updated_at DATETIME NOT NULL
    )
"""


async def _legacy_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.execute(text(APP_META_DDL))
        await connection.execute(text(LEGACY_TWITCH_ACCOUNTS_DDL))
        await connection.execute(
            text(
                "INSERT INTO twitch_accounts "
                "(id, user_id, access_token, connected_at, reconnect_required) "
                "VALUES (1, 7, 'legacy-token', '2026-01-01T00:00:00+00:00', 0), "
                "(2, 8, 'second-token', '2026-01-02T00:00:00+00:00', 1)"
            )
        )
    return engine


async def _columns(connection, table: str) -> list[str]:
    result = await connection.execute(text(f"PRAGMA table_info({table})"))
    return [str(row[1]) for row in result.all()]


@pytest.mark.asyncio
async def test_schema_migration_adds_client_id_and_preserves_rows():
    engine = await _legacy_engine()

    async with engine.begin() as connection:
        await run_schema_migrations(connection)

        assert "client_id" in await _columns(connection, "twitch_accounts")
        rows = (
            await connection.execute(
                text(
                    "SELECT user_id, access_token, client_id, reconnect_required "
                    "FROM twitch_accounts ORDER BY id"
                )
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            (7, "legacy-token", "", 0),
            (8, "second-token", "", 1),
        ]
        flag = await connection.execute(
            text("SELECT value FROM app_meta WHERE key = :key"),
            {"key": SCHEMA_MIGRATION_KEY},
        )
        assert flag.scalar_one() == "done"

    await engine.dispose()


@pytest.mark.asyncio
async def test_schema_migration_rerun_is_a_noop():
    engine = await _legacy_engine()

    async with engine.begin() as connection:
        await run_schema_migrations(connection)
        await run_schema_migrations(connection)
        await run_schema_migrations(connection)

        assert (await _columns(connection, "twitch_accounts")).count("client_id") == 1
        count = await connection.execute(text("SELECT COUNT(*) FROM twitch_accounts"))
        assert count.scalar_one() == 2
        flag_count = await connection.execute(
            text("SELECT COUNT(*) FROM app_meta WHERE key = :key"),
            {"key": SCHEMA_MIGRATION_KEY},
        )
        assert flag_count.scalar_one() == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_database_has_client_id_and_device_flow_table():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        assert "client_id" in await _columns(connection, "twitch_accounts")
        tables = await connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
        assert "twitch_device_flows" in {row[0] for row in tables.all()}

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_migrates_an_existing_database(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'existing.db'}")

    async with engine.begin() as connection:
        await connection.execute(text(APP_META_DDL))
        await connection.execute(text(LEGACY_TWITCH_ACCOUNTS_DDL))
        await connection.execute(
            text(
                "INSERT INTO twitch_accounts "
                "(id, user_id, access_token, connected_at) "
                "VALUES (1, 7, 'legacy-token', '2026-01-01T00:00:00+00:00')"
            )
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(
        "app.core.migrations.get_settings",
        lambda: db.get_settings().model_copy(
            update={
                "owner_twitch_id": "",
                "registration_code": "",
                "registration_open": False,
            }
        ),
    )
    await db.init_db()

    async with engine.connect() as connection:
        assert "client_id" in await _columns(connection, "twitch_accounts")
        row = await connection.execute(
            text("SELECT access_token, client_id FROM twitch_accounts WHERE id = 1")
        )
        assert tuple(row.one()) == ("legacy-token", "")
        flag = await connection.execute(
            text("SELECT value FROM app_meta WHERE key = :key"),
            {"key": SCHEMA_MIGRATION_KEY},
        )
        assert flag.scalar_one() == "done"

    await engine.dispose()
