import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import db


@pytest.mark.asyncio
async def test_init_db_adds_missing_user_composite_index_to_existing_table(
    tmp_path, monkeypatch
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'existing.db'}")

    # Simulate a database created before the composite index existed: the
    # table is present but the index is not.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE user_progress_snapshots ("
                "id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL, "
                "drop_id VARCHAR(128) NOT NULL, "
                "current_minutes INTEGER NOT NULL, "
                "recorded_at DATETIME NOT NULL)"
            )
        )

    monkeypatch.setattr(db, "engine", engine)
    await db.init_db()

    async with engine.connect() as connection:
        indexes = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_indexes(
                "user_progress_snapshots"
            )
        )

    index_names = {index["name"] for index in indexes}
    assert "ix_user_progress_snapshots_user_drop_recorded" in index_names

    await engine.dispose()
