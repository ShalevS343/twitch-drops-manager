"""Small shared fixtures for user-scoped tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.domain.models import TwitchAccount, User
from app.repositories.user_games import UserGameRepository


async def make_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def create_user(
    session,
    *,
    twitch_user_id: str = "1",
    login: str = "one",
    role: str = "user",
    display_name: str | None = None,
    telegram_chat_id: str = "",
    telegram_enabled: bool = False,
    games: list[str] | None = None,
) -> User:
    user = User(
        twitch_user_id=twitch_user_id,
        login=login,
        display_name=login if display_name is None else display_name,
        role=role,
        telegram_chat_id=telegram_chat_id,
        telegram_enabled=telegram_enabled,
    )
    session.add(user)
    await session.flush()
    if games:
        await UserGameRepository(session).replace(user.id, games)
    return user


async def connect_account(
    session,
    user: User,
    *,
    access_token: str = "token",
    expires_at: datetime | None = None,
    reconnect_required: bool = False,
    last_error: str = "",
    client_id: str = "",
) -> TwitchAccount:
    account = TwitchAccount(
        user_id=user.id,
        access_token=access_token,
        client_id=client_id,
        expires_at=expires_at,
        connected_at=datetime.now(timezone.utc),
        reconnect_required=reconnect_required,
        last_error=last_error,
    )
    session.add(account)
    await session.flush()
    return account


def future(minutes: int = 60) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def past(minutes: int = 60) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)
