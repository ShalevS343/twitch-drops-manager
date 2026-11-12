from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AccountConflictError,
    AccountDisabledError,
    InvalidAuthRequestError,
    LastAdminError,
    NotConfiguredError,
    ProviderError,
    RegistrationClosedError,
)
from app.core.security import compare_secrets, create_auth_session
from app.domain.models import (
    User,
    UserCampaignCompletion,
    UserCampaignStart,
    UserDropProgress,
    UserNotification,
    UserProgressSnapshot,
    UserSession,
    UserWatchFocus,
)
from app.repositories.twitch_accounts import TwitchAccountRepository
from app.repositories.user_games import UserGameRepository
from app.repositories.user_sessions import UserSessionRepository
from app.repositories.users import UserRepository


@dataclass(frozen=True)
class RegistrationState:
    open: bool
    invite_required: bool


@dataclass(frozen=True)
class AuthResult:
    user: User
    session_row: UserSession
    session_token: str
    csrf_token: str
    created: bool


class AuthService:
    """Registration, login, logout, and per-user account settings."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        provider=None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.provider = provider
        self.users = UserRepository(session)
        self.sessions = UserSessionRepository(session)
        self.accounts = TwitchAccountRepository(session)
        self.games = UserGameRepository(session)

    async def registration_state(self) -> RegistrationState:
        if await self.users.count() == 0:
            return RegistrationState(open=True, invite_required=False)
        if self.settings.registration_code.strip():
            return RegistrationState(open=True, invite_required=True)
        return RegistrationState(
            open=bool(self.settings.registration_open), invite_required=False
        )

    async def connect(
        self,
        redirect_url: str,
        invite_code: str = "",
        current_user: User | None = None,
    ) -> AuthResult:
        token = self.provider.parse_oauth_token(redirect_url)
        if not token:
            raise InvalidAuthRequestError(
                "Could not find an access token in the pasted URL"
            )

        try:
            info = await self.provider.validate(token)
        except NotConfiguredError as exc:
            raise InvalidAuthRequestError(str(exc)) from exc

        expected_client = self.settings.gql_client_id
        if str(info.get("client_id") or "") != expected_client:
            raise InvalidAuthRequestError(
                "That token was issued for a different Twitch client. "
                "Use the Connect Twitch link on this page and paste the URL "
                "Twitch redirects you to."
            )

        twitch_user_id = str(info.get("user_id") or "").strip()
        login = str(info.get("login") or "").strip()
        if not twitch_user_id or not login:
            raise InvalidAuthRequestError(
                "Twitch did not return the account identity; try connecting again"
            )

        expires_at = self._expires_at(info)
        user = await self.users.get_by_twitch_id(twitch_user_id)
        created = False

        if user is not None:
            if current_user is not None and current_user.id != user.id:
                raise AccountConflictError(
                    "Sign out before connecting a different Twitch account"
                )
            if not user.is_active:
                raise AccountDisabledError("This account has been disabled")
        else:
            if current_user is not None:
                raise AccountConflictError(
                    "Sign out before connecting a different Twitch account"
                )
            if not await self._registration_allowed(invite_code):
                raise RegistrationClosedError(
                    "Registration is closed; a valid invite code is required"
                )
            first_user = await self.users.claim_first_admin_slot()
            user = await self.users.create(
                twitch_user_id=twitch_user_id,
                login=login,
                role="admin" if first_user else "user",
            )
            created = True

        # Seed defaults exactly once. A user who clears all games must keep the
        # empty selection on later logins.
        if not user.games_seeded:
            await self.games.seed_defaults(
                user.id, self.settings.default_game_list
            )
            await self.users.set_games_seeded(user, True)

        display_name, profile_image_url = await self._profile(
            token, twitch_user_id, login
        )
        await self.users.update_profile(
            user,
            login=login,
            display_name=display_name,
            profile_image_url=profile_image_url,
        )
        await self.users.touch_login(user)
        await self.accounts.upsert(
            user_id=user.id,
            access_token=token,
            expires_at=expires_at,
            connected_at=datetime.now(timezone.utc),
            reconnect_required=False,
            last_error="",
        )
        session_token, csrf_token, session_row = await create_auth_session(
            self.session, user.id, self.settings.session_ttl_days
        )
        await self.session.commit()

        return AuthResult(
            user=user,
            session_row=session_row,
            session_token=session_token,
            csrf_token=csrf_token,
            created=created,
        )

    async def logout(self, raw_token: str | None) -> None:
        if raw_token:
            from app.core.security import hash_token

            await self.sessions.delete_by_token_hash(hash_token(raw_token))
        await self.session.commit()

    async def disconnect(self, user_id: int) -> None:
        await self.accounts.delete_for_user(user_id)
        for model in (
            UserDropProgress,
            UserProgressSnapshot,
            UserCampaignCompletion,
            UserWatchFocus,
            UserNotification,
            UserCampaignStart,
        ):
            await self.session.execute(delete(model).where(model.user_id == user_id))
        await self.session.commit()

    async def update_telegram(
        self, user_id: int, chat_id: str, enabled: bool
    ) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise InvalidAuthRequestError("User not found")

        chat_id = (chat_id or "").strip()
        if chat_id:
            owner = (
                await self.session.execute(
                    select(User)
                    .where(
                        func.trim(User.telegram_chat_id) == chat_id,
                        User.id != user.id,
                    )
                    .limit(1)
                )
            ).scalars().first()
            if owner is not None:
                raise AccountConflictError(
                    "This Telegram chat is already linked to another account"
                )

        await self.users.set_telegram(user, chat_id, enabled)
        if not enabled or not chat_id:
            await self.session.execute(
                delete(UserCampaignStart).where(
                    UserCampaignStart.user_id == user_id
                )
            )
        await self.session.commit()
        return user

    async def set_user_active(self, user_id: int, active: bool) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise InvalidAuthRequestError("User not found")

        if not active and user.role == "admin" and user.is_active:
            active_admins = await self.users.count_active_admins()
            if active_admins <= 1:
                raise LastAdminError(
                    "Cannot disable the last active admin account"
                )

        await self.users.set_active(user, active)
        if not active:
            await self.sessions.delete_for_user(user_id)
            # Do not deliver a backlog of campaign starts when this account is
            # enabled again.
            await self.session.execute(
                delete(UserCampaignStart).where(
                    UserCampaignStart.user_id == user_id
                )
            )
            focus = (
                await self.session.execute(
                    select(UserWatchFocus).where(UserWatchFocus.user_id == user_id)
                )
            ).scalar_one_or_none()
            if focus is not None:
                focus.enabled = False
                focus.status = "idle"
                focus.reason = "account disabled"
        await self.session.commit()
        return user

    async def _registration_allowed(self, invite_code: str) -> bool:
        if await self.users.count() == 0:
            return True

        configured = self.settings.registration_code.strip()
        if configured:
            supplied = (invite_code or "").strip()
            if not supplied:
                return False
            return compare_secrets(configured, supplied)
        return bool(self.settings.registration_open)

    async def _profile(
        self, token: str, twitch_user_id: str, login: str
    ) -> tuple[str, str]:
        display_name = login
        profile_image_url = ""
        try:
            profile = await self.provider.fetch_profile(token, twitch_user_id)
        except (NotConfiguredError, ProviderError):
            return display_name, profile_image_url

        display_name = str(profile.get("displayName") or login)
        profile_image_url = str(profile.get("profileImageURL") or "")
        return display_name, profile_image_url

    @staticmethod
    def _expires_at(info: dict) -> datetime | None:
        try:
            expires_in = int(info.get("expires_in") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        if expires_in <= 0:
            return None
        return datetime.now(timezone.utc) + timedelta(seconds=expires_in)
