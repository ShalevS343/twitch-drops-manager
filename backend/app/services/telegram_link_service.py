from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import NotConfiguredError, ProviderError
from app.core.security import hash_token
from app.domain.models import User, UserCampaignStart
from app.domain.schemas import TelegramLinkOut
from app.providers.telegram import TelegramProvider
from app.repositories.telegram_links import TelegramLinkRepository
from app.repositories.users import UserRepository

LINK_TTL = timedelta(minutes=10)

INVALID_CODE_MESSAGE = (
    "This link code is invalid or has expired. "
    "Open Telegram and send /start to the bot for a new code."
)


@dataclass(frozen=True)
class LinkResult:
    ok: bool
    message: str
    user: User | None = None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TelegramLinkService:
    """Create link codes, bind private chats, and unlink them."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: TelegramProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings or get_settings()
        self.links = TelegramLinkRepository(session)
        self.users = UserRepository(session)

    async def create_link(self, user_id: int) -> TelegramLinkOut:
        if not self.provider.configured:
            raise NotConfiguredError("Telegram bot token is not configured")

        me = await self.provider.get_me()
        username = str(me.get("username") or "").strip()
        if not username:
            raise ProviderError("Telegram bot username is unavailable")

        # A new request invalidates any earlier unused code for this user.
        await self.links.delete_for_user(user_id)

        now = datetime.now(timezone.utc)
        code = secrets.token_urlsafe(32)
        row = await self.links.create(
            user_id=user_id,
            code_hash=hash_token(code),
            expires_at=now + LINK_TTL,
        )
        await self.session.commit()

        return TelegramLinkOut(
            deep_link=f"https://t.me/{username}?start={code}",
            expires_at=row.expires_at,
        )

    async def link_chat(
        self, code: str, chat_id: str, chat_type: str = "private"
    ) -> LinkResult:
        chat_id = (chat_id or "").strip()
        if (chat_type or "").strip().lower() != "private" or not chat_id:
            return LinkResult(
                False,
                "Only private Telegram chats can be linked. "
                "Open the bot directly and send /start.",
            )

        code = (code or "").strip()
        if not code:
            return LinkResult(False, INVALID_CODE_MESSAGE)

        row = await self.links.get_by_hash(hash_token(code))
        now = datetime.now(timezone.utc)
        if row is None or row.used_at is not None or _aware(row.expires_at) <= now:
            return LinkResult(False, INVALID_CODE_MESSAGE)

        user = await self.session.get(User, row.user_id)
        if user is None or not user.is_active:
            return LinkResult(False, INVALID_CODE_MESSAGE)

        owner = (
            await self.session.execute(
                select(User)
                .where(
                    User.telegram_chat_id == chat_id,
                    User.id != user.id,
                )
                .limit(1)
            )
        ).scalars().first()
        if owner is not None:
            return LinkResult(
                False,
                "This Telegram chat is already linked to another account. "
                "Send /unlink there first.",
            )

        user.telegram_chat_id = chat_id
        user.telegram_enabled = True
        await self.links.mark_used(row, now)
        await self.session.commit()

        display_name = (
            user.display_name.strip()
            or user.login.strip()
            or "your Twitch account"
        )
        return LinkResult(
            True,
            f"Connected to Twitch Drops Manager as {display_name}. "
            "Alerts are on. Send /stop to stop alerts.",
            user,
        )

    async def unlink(self, user_id: int) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise LookupError("User not found")

        user.telegram_chat_id = ""
        user.telegram_enabled = False
        await self._delete_pending_starts(user_id)
        await self.links.delete_for_user(user_id)
        await self.session.commit()
        return user

    async def disable_for_chat(self, chat_id: str) -> User | None:
        """Turn alerts off for the user owning this chat id."""
        user = await self._user_for_chat(chat_id)
        if user is None:
            return None

        user.telegram_enabled = False
        await self._delete_pending_starts(user.id)
        await self.session.commit()
        return user

    async def unlink_chat(self, chat_id: str) -> User | None:
        user = await self._user_for_chat(chat_id)
        if user is None:
            return None
        return await self.unlink(user.id)

    async def _user_for_chat(self, chat_id: str) -> User | None:
        chat_id = (chat_id or "").strip()
        if not chat_id:
            return None
        result = await self.session.execute(
            select(User)
            .where(func.trim(User.telegram_chat_id) == chat_id)
            .order_by(User.id)
            .limit(1)
        )
        return result.scalars().first()

    async def _delete_pending_starts(self, user_id: int) -> None:
        await self.session.execute(
            delete(UserCampaignStart).where(
                UserCampaignStart.user_id == user_id
            )
        )
