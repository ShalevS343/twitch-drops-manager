import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.exc import CompileError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_directory(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    path = url.split(":///", 1)[-1]
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory(settings.database_url)

_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"timeout": 30} if _is_sqlite else {}

engine = create_async_engine(
    settings.database_url,
    future=True,
    connect_args=_connect_args,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _create_missing_indexes(connection) -> None:
    """Create model indexes that ``create_all`` skipped on existing tables."""
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            try:
                index.create(connection, checkfirst=True)
            except (CompileError, IntegrityError, OperationalError) as exc:
                # A legacy database may already contain duplicate Telegram chat
                # ids. Do not block startup: the link service still enforces
                # uniqueness with a trimmed lookup, and the index is created as
                # soon as the data is cleaned up.
                logger.warning(
                    "Could not create index %s (%s); continuing",
                    index.name,
                    type(exc).__name__,
                )


async def init_db() -> None:
    from app.core.migrations import run_multi_user_migration
    from app.domain import models  # noqa: F401

    last_error: OperationalError | None = None

    for attempt in range(10):
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.run_sync(_create_missing_indexes)
                await run_multi_user_migration(connection)
            return
        except OperationalError as exc:
            last_error = exc
            await asyncio.sleep(0.5 * (attempt + 1))

    if last_error is not None:
        raise last_error
