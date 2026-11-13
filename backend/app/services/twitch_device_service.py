"""Twitch Smart TV device-code login orchestration."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AuthError,
    DeviceFlowAccessDeniedError,
    DeviceFlowDeniedError,
    DeviceFlowExpiredError,
    DeviceFlowExpiredTokenError,
    DeviceFlowNotFoundError,
    DeviceFlowPendingError,
    DeviceFlowSlowDownError,
    DeviceFlowTerminalError,
    InvalidAuthRequestError,
    ProviderError,
)
from app.domain.models import User
from app.providers.twitch_user import TwitchUserProvider
from app.repositories.twitch_device_flows import TwitchDeviceFlowRepository
from app.services.auth_service import AuthResult, AuthService

DEVICE_FLOW_TTL_SECONDS = 30 * 60
DEFAULT_INTERVAL_SECONDS = 5
SLOW_DOWN_INCREMENT_SECONDS = 5


@dataclass(frozen=True)
class DeviceFlowStart:
    flow_id: str
    user_code: str
    verification_uri: str
    expires_at: datetime
    interval: int


@dataclass(frozen=True)
class DevicePollResult:
    pending: bool
    interval: int
    auth: AuthResult | None = None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


class TwitchDeviceService:
    """Start, poll, and cancel one Twitch device authorization.

    The service owns the upstream poll cadence. A browser poll inside the stored
    interval returns ``pending`` without contacting Twitch, so duplicate tabs
    cannot trigger ``slow_down`` or consume the one-time flow.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        provider: TwitchUserProvider | None = None,
    ) -> None:
        from app.services.factory import get_twitch_user_provider

        self.session = session
        self.settings = settings or get_settings()
        self.provider = provider or get_twitch_user_provider()
        self.flows = TwitchDeviceFlowRepository(session)

    async def start(
        self,
        invite_code: str = "",
        current_user: User | None = None,
    ) -> DeviceFlowStart:
        await self.flows.delete_expired()
        await self.session.commit()

        body = await self.provider.start_device_flow()
        device_code = str(body.get("device_code") or "").strip()
        user_code = str(body.get("user_code") or "").strip()
        verification_uri = str(
            body.get("verification_uri") or body.get("verification_url") or ""
        ).strip()
        if not device_code or not user_code or not verification_uri:
            raise ProviderError(
                "Twitch device authorization failed (invalid response)"
            )

        now = datetime.now(timezone.utc)
        ttl = min(
            DEVICE_FLOW_TTL_SECONDS,
            _positive_int(body.get("expires_in"), DEVICE_FLOW_TTL_SECONDS),
        )
        expires_at = now + timedelta(seconds=ttl)
        interval = _positive_int(body.get("interval"), DEFAULT_INTERVAL_SECONDS)

        flow = await self.flows.create(
            flow_id=secrets.token_urlsafe(32),
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            client_id=self.settings.device_grant_client_id,
            invite_code=(invite_code or "").strip(),
            current_user_id=current_user.id if current_user is not None else None,
            interval_seconds=interval,
            expires_at=expires_at,
        )
        await self.session.commit()
        return DeviceFlowStart(
            flow_id=flow.flow_id,
            user_code=flow.user_code,
            verification_uri=flow.verification_uri,
            expires_at=flow.expires_at,
            interval=flow.interval_seconds,
        )

    async def _mark_terminal(
        self, flow_id: str, status: str
    ) -> bool:
        """Persist a terminal status without ever downgrading ``connected``."""
        changed = await self.flows.set_status(flow_id, status)
        await self.session.commit()
        return changed

    async def poll(self, flow_id: str) -> DevicePollResult:
        now = datetime.now(timezone.utc)
        flow = await self.flows.get_by_flow_id(flow_id)
        if flow is None or flow.status != "pending":
            raise DeviceFlowNotFoundError("This login code is no longer valid")

        expires_at = _aware(flow.expires_at)
        if expires_at is not None and expires_at <= now:
            if not await self._mark_terminal(flow_id, "expired"):
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                )
            raise DeviceFlowExpiredError(
                "This login code expired; start a new one"
            )

        not_after = now - timedelta(seconds=flow.interval_seconds)
        claimed = await self.flows.claim_poll(
            flow_id, now=now, not_after=not_after
        )
        if not claimed:
            # Another tab/request holds this cadence slot. Re-read so a flow
            # that just completed or expired is reported correctly.
            flow = await self.flows.get_by_flow_id(flow_id)
            if flow is None or flow.status != "pending":
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                )
            expires_at = _aware(flow.expires_at)
            if expires_at is not None and expires_at <= now:
                if not await self._mark_terminal(flow_id, "expired"):
                    raise DeviceFlowNotFoundError(
                        "This login code is no longer valid"
                    )
                raise DeviceFlowExpiredError(
                    "This login code expired; start a new one"
                )
            return DevicePollResult(
                pending=True, interval=flow.interval_seconds
            )

        # Persist the atomic claim before the network call. A duplicate request
        # can no longer enter the upstream poll until the interval elapses.
        await self.session.commit()
        flow = await self.flows.get_by_flow_id(flow_id)
        if flow is None or flow.status != "pending":
            raise DeviceFlowNotFoundError("This login code is no longer valid")

        try:
            token_body = await self.provider.poll_device_token(
                flow.device_code, flow.client_id
            )
        except DeviceFlowPendingError:
            return DevicePollResult(pending=True, interval=flow.interval_seconds)
        except DeviceFlowSlowDownError:
            flow.interval_seconds += SLOW_DOWN_INCREMENT_SECONDS
            await self.session.commit()
            return DevicePollResult(pending=True, interval=flow.interval_seconds)
        except DeviceFlowExpiredTokenError:
            if not await self._mark_terminal(flow_id, "expired"):
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                ) from None
            raise DeviceFlowExpiredError(
                "This login code expired; start a new one"
            ) from None
        except DeviceFlowAccessDeniedError:
            if not await self._mark_terminal(flow_id, "denied"):
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                ) from None
            raise DeviceFlowDeniedError(
                "Twitch authorization was denied"
            ) from None
        except DeviceFlowTerminalError as exc:
            if not await self._mark_terminal(flow_id, "error"):
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                ) from exc
            raise InvalidAuthRequestError(
                "Twitch could not complete the login; start a new code"
            ) from exc
        except ProviderError:
            # Network errors and Twitch 5xx/429 responses are transient. The
            # cadence claim above already prevents a tight retry loop, so keep
            # the flow pending instead of failing the login.
            return DevicePollResult(pending=True, interval=flow.interval_seconds)

        token = str(token_body.get("access_token") or "").strip()
        if not token:
            if not await self._mark_terminal(flow_id, "error"):
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                )
            raise InvalidAuthRequestError(
                "Twitch could not complete the login; start a new code"
            )

        try:
            info = await self.provider.validate(token)
        except ProviderError as exc:
            if not await self._mark_terminal(flow_id, "error"):
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                ) from exc
            raise InvalidAuthRequestError(
                "Twitch rejected the login; start a new code"
            ) from exc

        expected_client = flow.client_id or self.settings.device_grant_client_id
        if str(info.get("client_id") or "") != expected_client:
            if not await self._mark_terminal(flow_id, "error"):
                raise DeviceFlowNotFoundError(
                    "This login code is no longer valid"
                )
            raise InvalidAuthRequestError(
                "That Twitch token was issued for a different client"
            )

        current_user = None
        if flow.current_user_id is not None:
            current_user = await self.session.get(User, flow.current_user_id)

        try:
            result = await AuthService(
                self.session, settings=self.settings, provider=self.provider
            ).complete_login(
                token,
                info,
                invite_code=flow.invite_code,
                current_user=current_user,
                client_id=expected_client,
            )
        except AuthError:
            # The Twitch device code has been consumed; never allow a retry on
            # the same row (for example after fixing an invite code).
            await self._mark_terminal(flow_id, "error")
            raise

        interval = flow.interval_seconds
        await self.flows.set_status(flow_id, "connected")
        await self.session.commit()
        return DevicePollResult(
            pending=False,
            interval=interval,
            auth=result,
        )

    async def cancel(self, flow_id: str) -> None:
        await self.flows.delete(flow_id)
        await self.session.commit()
