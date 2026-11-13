from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
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
        invite_code_configured = bool(self.settings.registration_code.strip())
        owner_configured = bool(self.settings.owner_twitch_id.strip())
        open_registration = bool(self.settings.registration_open)

        if await self.users.count() == 0:
            # A gate must exist for the very first user too. OWNER_TWITCH_ID is
            # checked against the connecting Twitch id in ``connect``; the UI
            # only needs to know whether registration is possible at all.
            if invite_code_configured:
                return RegistrationState(open=True, invite_required=True)
            return RegistrationState(
                open=owner_configured or open_registration,
                invite_required=False,
            )

        if invite_code_configured:
            return RegistrationState(open=True, invite_required=True)
        return RegistrationState(
            open=open_registration, invite_required=False
        )

    async def connect(
        self,
        redirect_url: str,
        invite_code: str = "",
        current_user: User | None = None,
    ) -> AuthResult:
        """Implicit-grant login from a pasted Twitch redirect URL.

        The implicit flow must stay on the Android client: the Smart TV client
        does not accept the implicit grant and the Android token is the one GQL
        already accepts for existing accounts.
        """
        token = self.provider.parse_oauth_token(redirect_url)
        if not token:
            raise InvalidAuthRequestError(
                "Could not find an access token in the pasted URL"
            )

        try:
            info = await self.provider.validate(token)
        except NotConfiguredError as exc:
            raise InvalidAuthRequestError(str(exc)) from exc

        expected_client = self.settings.device_client_id
        if str(info.get("client_id") or "") != expected_client:
            raise InvalidAuthRequestError(
                "That token was issued for a different Twitch client. "
                "Use Connect with code on this page, or the advanced "
                "paste-URL flow with the URL Twitch redirects you to."
            )

        return await self.complete_login(
            token,
            info,
            invite_code=invite_code,
            current_user=current_user,
            client_id=expected_client,
        )

    async def complete_login(
        self,
        token: str,
        info: dict,
        *,
        invite_code: str,
        current_user: User | None,
        client_id: str,
    ) -> AuthResult:
        """Validate the user and create the app session for any login flow.

        The caller has already validated ``token`` and checked that the token's
        issuing client id matches its flow. This method owns the shared
        user/registration/session side effects.
        """
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
            if not await self._registration_allowed(twitch_user_id, invite_code):
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
            token, twitch_user_id, login, client_id
        )
        await self.users.update_profile(
            user,
            login=login,
            display_name=display_name,
            profile_image_url=profile_image_url,
        )
        await self.users.touch_login(user)
        await self.accounts.save(
            user_id=user.id,
            access_token=token,
            expires_at=expires_at,
            connected_at=datetime.now(timezone.utc),
            reconnect_required=False,
            last_error="",
            client_id=client_id,
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

    async def update_telegram(self, user_id: int, enabled: bool) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise InvalidAuthRequestError("User not found")

        chat_id = (user.telegram_chat_id or "").strip()
        if enabled and not chat_id:
            raise InvalidAuthRequestError(
                "Connect Telegram with the link before enabling alerts"
            )

        await self.users.set_telegram(user, chat_id, enabled)
        if not enabled:
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

        if not active:
            # One conditional UPDATE checks "is this the last active admin?"
            # at write time, so two concurrent demotions cannot both pass a
            # read-then-write check and leave the install without an admin.
            deactivated = await self.users.deactivate_unless_last_admin(user_id)
            if not deactivated:
                await self.session.refresh(user)
                if user.is_active and user.role == "admin":
                    raise LastAdminError(
                        "Cannot disable the last active admin account"
                    )
                # Already inactive: still run the idempotent cleanup below.
            else:
                user.is_active = False

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
        else:
            await self.users.set_active(user, True)
        await self.session.commit()
        return user

    async def _registration_allowed(
        self, twitch_user_id: str, invite_code: str
    ) -> bool:
        configured_code = self.settings.registration_code.strip()
        owner_id = self.settings.owner_twitch_id.strip()
        supplied_code = (invite_code or "").strip()
        first_user = await self.users.count() == 0

        if first_user:
            # A fresh install is never open just because the table is empty.
            # Bootstrap requires an explicit owner, invite code, or opt-in.
            if owner_id and compare_secrets(
                owner_id, (twitch_user_id or "").strip()
            ):
                return True
            if configured_code:
                return bool(supplied_code) and compare_secrets(
                    configured_code, supplied_code
                )
            return bool(self.settings.registration_open)

        if configured_code:
            if not supplied_code:
                return False
            return compare_secrets(configured_code, supplied_code)
        return bool(self.settings.registration_open)

    async def _profile(
        self,
        token: str,
        twitch_user_id: str,
        login: str,
        client_id: str,
    ) -> tuple[str, str]:
        display_name = login
        profile_image_url = ""
        try:
            profile = await self.provider.fetch_profile(
                token, twitch_user_id, client_id=client_id
            )
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
