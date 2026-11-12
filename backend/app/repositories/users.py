from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import TwitchAccount, User, UserWatchFocus

FIRST_ADMIN_KEY = "first_admin_claimed"


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_twitch_id(self, twitch_user_id: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.twitch_user_id == twitch_user_id)
        )
        return result.scalar_one_or_none()

    async def list(self) -> list[User]:
        result = await self.session.execute(
            select(User).order_by(User.login, User.id)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(User))
        return int(result.scalar_one())

    async def list_active_ids_with_accounts(self) -> list[int]:
        result = await self.session.execute(
            select(User.id)
            .join(TwitchAccount, TwitchAccount.user_id == User.id)
            .where(User.is_active.is_(True))
            .order_by(User.id)
        )
        return [int(user_id) for user_id in result.scalars().all()]

    async def list_active_with_telegram(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.is_active.is_(True),
                User.telegram_enabled.is_(True),
                func.trim(User.telegram_chat_id) != "",
            )
            .order_by(User.id)
        )
        return list(result.scalars().all())

    async def list_active_ids_with_focus(self) -> list[int]:
        result = await self.session.execute(
            select(User.id)
            .join(UserWatchFocus, UserWatchFocus.user_id == User.id)
            .where(
                User.is_active.is_(True),
                UserWatchFocus.enabled.is_(True),
            )
            .order_by(User.id)
        )
        return [int(user_id) for user_id in result.scalars().all()]

    async def list_ids_missing_profile(self) -> list[int]:
        """Active connected users without a stored Twitch profile."""
        result = await self.session.execute(
            select(User.id)
            .join(TwitchAccount, TwitchAccount.user_id == User.id)
            .where(
                User.is_active.is_(True),
                User.display_name == "",
            )
            .order_by(User.id)
        )
        return [int(user_id) for user_id in result.scalars().all()]

    async def count_active_admins(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
        return int(result.scalar_one())

    async def claim_first_admin_slot(self) -> bool:
        """Atomically claim the one-time first-admin bootstrap.

        The claim, the users-exist check, and the insert are one statement.
        ``app_meta`` is a single-row-per-key table, so only one concurrent
        registration can insert the key and win the admin role.
        """
        result = await self.session.execute(
            text(
                "INSERT OR IGNORE INTO app_meta (key, value, updated_at) "
                "SELECT :key, '1', :now "
                "WHERE NOT EXISTS (SELECT 1 FROM users)"
            ),
            {
                "key": FIRST_ADMIN_KEY,
                "now": datetime.now(timezone.utc).isoformat(),
            },
        )
        return result.rowcount == 1

    async def create(
        self,
        *,
        twitch_user_id: str,
        login: str,
        display_name: str = "",
        profile_image_url: str = "",
        role: str = "user",
        telegram_chat_id: str = "",
        telegram_enabled: bool = False,
    ) -> User:
        user = User(
            twitch_user_id=twitch_user_id.strip(),
            login=login.strip(),
            display_name=(display_name or login).strip(),
            profile_image_url=profile_image_url,
            role=role,
            telegram_chat_id=(telegram_chat_id or "").strip(),
            telegram_enabled=telegram_enabled,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_profile(
        self,
        user: User,
        *,
        login: str,
        display_name: str,
        profile_image_url: str,
    ) -> User:
        user.login = login.strip()
        user.display_name = (display_name or login).strip()
        user.profile_image_url = profile_image_url
        await self.session.flush()
        return user

    async def touch_login(self, user: User, when: datetime | None = None) -> User:
        user.last_login_at = when or datetime.now(timezone.utc)
        await self.session.flush()
        return user

    async def set_active(self, user: User, active: bool) -> User:
        user.is_active = active
        await self.session.flush()
        return user

    async def set_games_seeded(self, user: User, seeded: bool = True) -> User:
        user.games_seeded = seeded
        await self.session.flush()
        return user

    async def set_telegram(
        self, user: User, chat_id: str, enabled: bool
    ) -> User:
        user.telegram_chat_id = chat_id.strip()
        user.telegram_enabled = enabled
        await self.session.flush()
        return user
