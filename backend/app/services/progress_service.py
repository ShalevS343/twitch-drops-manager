import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotConfiguredError, ProviderError
from app.domain.models import TwitchAuth
from app.domain.parsing import parse_inventory
from app.providers.telegram import TelegramProvider
from app.providers.twitch_user import TwitchUserProvider
from app.repositories.notifications import NotificationRepository
from app.repositories.progress import ProgressRepository
from app.repositories.twitch_auth import TwitchAuthRepository

logger = logging.getLogger(__name__)

TOKEN_REFRESH_MARGIN = timedelta(minutes=5)


@dataclass
class ProgressResult:
    connected: bool
    campaign_count: int
    drop_count: int
    notified_count: int


class ProgressService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: TwitchUserProvider,
        telegram: TelegramProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.telegram = telegram

    async def run(self) -> ProgressResult:
        auth = await TwitchAuthRepository(self.session).get()
        if auth is None:
            return ProgressResult(
                connected=False, campaign_count=0, drop_count=0, notified_count=0
            )

        auth = await self._ensure_token(auth)
        inventory = await self.provider.fetch_inventory(auth.access_token)

        campaigns = inventory.get("dropCampaignsInProgress") or []
        if not isinstance(campaigns, list):
            campaigns = []

        rows = parse_inventory(campaigns)
        await ProgressRepository(self.session).replace(rows)
        await self.session.commit()

        notified = await self._notify(rows)
        await self.session.commit()

        campaign_count = len(
            {row["campaign_gql_id"] for row in rows if row["campaign_gql_id"]}
        )
        return ProgressResult(
            connected=True,
            campaign_count=campaign_count,
            drop_count=len(rows),
            notified_count=notified,
        )

    async def _ensure_token(self, auth: TwitchAuth) -> TwitchAuth:
        expires = auth.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        if (
            auth.access_token
            and expires is not None
            and expires - TOKEN_REFRESH_MARGIN > datetime.now(timezone.utc)
        ):
            return auth

        # Legacy implicit tokens report expires_in=0, i.e. no known expiry.
        if auth.access_token and expires is None:
            return auth

        if not auth.refresh_token:
            raise NotConfiguredError("Twitch login expired; reconnect your account")

        data = await self.provider.refresh(auth.refresh_token)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(data.get("expires_in") or 0)
        )

        auth = await TwitchAuthRepository(self.session).save(
            user_id=auth.user_id,
            login=auth.login,
            access_token=str(data["access_token"]),
            refresh_token=str(data.get("refresh_token") or auth.refresh_token),
            expires_at=expires_at,
        )
        await self.session.commit()
        return auth

    async def _notify(self, rows: list[dict]) -> int:
        if not self.telegram.configured:
            return 0

        repo = NotificationRepository(self.session)
        sent = 0

        for row in rows:
            if not row["is_ready"]:
                continue

            dedupe_key = f"drop-ready:{row['drop_id']}"
            if await repo.exists(dedupe_key):
                continue

            message = (
                "Twitch drop ready to claim!\n"
                f"Game: {row['game_name'] or 'Unknown'}\n"
                f"Campaign: {row['campaign_name']}\n"
                f"Drop: {row['drop_name']}\n"
                f"Watched: {row['current_minutes']}/{row['required_minutes']} min\n"
                "Claim it at https://www.twitch.tv/drops/inventory"
            )

            try:
                await self.telegram.send(message)
            except ProviderError as exc:
                logger.warning("Telegram notification failed: %s", exc)
                continue

            await repo.mark_sent(dedupe_key)
            sent += 1

        return sent
