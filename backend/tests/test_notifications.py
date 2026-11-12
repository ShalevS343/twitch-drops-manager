import pytest
from sqlalchemy import func, select

from app.domain.models import UserNotification
from app.repositories.notifications import NotificationRepository
from tests.support import create_user, make_engine


@pytest.mark.asyncio
async def test_claim_rejects_duplicate_key_for_the_same_user():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()

        repo = NotificationRepository(session, user.id)
        assert await repo.claim("dup") is True
        assert await repo.claim("dup") is False
        await session.commit()

        total = await session.scalar(
            select(func.count()).select_from(UserNotification)
        )
        assert total == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_rejects_key_claimed_by_another_session_for_the_same_user():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()
        user_id = user.id

    async with factory() as first_session:
        assert (
            await NotificationRepository(first_session, user_id).claim("shared")
        ) is True
        await first_session.commit()

    async with factory() as second_session:
        assert (
            await NotificationRepository(second_session, user_id).claim("shared")
        ) is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_release_allows_key_to_be_claimed_again():
    engine, factory = await make_engine()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        await session.commit()

        repo = NotificationRepository(session, user.id)
        assert await repo.claim("retry") is True
        await repo.release("retry")
        assert await repo.claim("retry") is True
        await session.commit()

        total = await session.scalar(
            select(func.count()).select_from(UserNotification)
        )
        assert total == 1

    await engine.dispose()
