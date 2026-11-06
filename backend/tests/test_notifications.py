import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.domain.models import Notification
from app.repositories.notifications import NotificationRepository


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


@pytest.mark.asyncio
async def test_claim_rejects_duplicate_key_in_same_session():
    engine, factory = await _session()

    async with factory() as session:
        repo = NotificationRepository(session)
        assert await repo.claim("dup") is True
        assert await repo.claim("dup") is False
        await session.commit()

        total = await session.scalar(select(func.count()).select_from(Notification))
        assert total == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_rejects_key_claimed_by_another_session():
    engine, factory = await _session()

    async with factory() as first_session:
        assert await NotificationRepository(first_session).claim("shared") is True
        await first_session.commit()

    async with factory() as second_session:
        assert await NotificationRepository(second_session).claim("shared") is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_release_allows_key_to_be_claimed_again():
    engine, factory = await _session()

    async with factory() as session:
        repo = NotificationRepository(session)
        assert await repo.claim("retry") is True
        await repo.release("retry")
        assert await repo.claim("retry") is True
        await session.commit()

        total = await session.scalar(select(func.count()).select_from(Notification))
        assert total == 1

    await engine.dispose()
