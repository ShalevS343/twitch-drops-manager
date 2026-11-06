import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotConfiguredError, ProviderError
from app.domain.models import TwitchAuth
from app.domain.parsing import parse_inventory, parse_iso_datetime
from app.providers.telegram import TelegramProvider
from app.providers.twitch_user import TwitchUserProvider
from app.repositories.notifications import NotificationRepository
from app.repositories.progress import ProgressRepository
from app.repositories.twitch_auth import TwitchAuthRepository

logger = logging.getLogger(__name__)

TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
SNAPSHOT_RETENTION = timedelta(hours=24)


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
        now = datetime.now(timezone.utc)
        repo = ProgressRepository(self.session)
        await repo.replace(rows)
        await repo.add_snapshots(rows)
        await repo.prune_snapshots(now - SNAPSHOT_RETENTION)
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

        events: list[tuple[str, str]] = []

        for row in rows:
            if not row["is_ready"] or row["is_claimed"]:
                continue
            events.append(
                (
                    f"drop-ready:{row['drop_id']}",
                    (
                        "• Ready to claim: "
                        f"{row['drop_name']} ({row['campaign_name']}, "
                        f"{row['game_name'] or 'Unknown'})"
                    ),
                )
            )

        now = datetime.now(timezone.utc)
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            if row["is_claimed"]:
                continue
            campaign_id = row["campaign_gql_id"]
            if not campaign_id:
                continue
            grouped.setdefault(campaign_id, []).append(row)

        for campaign_id, campaign_rows in grouped.items():
            ends_at = parse_iso_datetime(campaign_rows[0].get("campaign_ends_at"))
            if ends_at is None:
                continue

            hours_left = (ends_at - now).total_seconds() / 3600
            if hours_left <= 0:
                continue

            # Send only the tightest applicable window per campaign per run.
            if hours_left <= 2:
                suffix = "2h"
            elif hours_left <= 24:
                suffix = "24h"
            else:
                continue

            total_remaining = sum(
                max(0, int(row["required_minutes"]) - int(row["current_minutes"]))
                for row in campaign_rows
            )
            events.append(
                (
                    f"campaign-ending:{campaign_id}:{suffix}",
                    (
                        f"• {campaign_rows[0]['campaign_name']} ends in ~{suffix}; "
                        f"{len(campaign_rows)} drops left ({total_remaining} min)"
                    ),
                )
            )

        if not events:
            return 0

        repo = NotificationRepository(self.session)
        claimed: list[tuple[str, str]] = []
        for key, line in events:
            if await repo.claim(key):
                claimed.append((key, line))

        if not claimed:
            return 0

        lines = ["Twitch Drops update", *(line for _, line in claimed)]
        if any(key.startswith("drop-ready:") for key, _ in claimed):
            lines.append("Claim: https://www.twitch.tv/drops/inventory")
        message = "\n".join(lines)

        try:
            await self.telegram.send(message)
        except ProviderError as exc:
            logger.warning("Telegram notification failed: %s", exc)
            for key, _ in claimed:
                await repo.release(key)
            return 0

        return len(claimed)
