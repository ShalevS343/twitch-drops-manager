import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    NotConfiguredError,
    ProviderError,
    ReconnectRequiredError,
)
from app.domain.models import TwitchAccount, User
from app.domain.parsing import (
    campaign_gql_id_from_external_id,
    parse_earned_rewards,
    parse_inventory,
    parse_iso_datetime,
)
from app.providers.telegram import TelegramProvider
from app.providers.twitch_user import TwitchUserProvider
from app.repositories.campaign_completions import CampaignCompletionRepository
from app.repositories.campaigns import CampaignRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.progress import ProgressRepository
from app.repositories.twitch_accounts import TwitchAccountRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

SNAPSHOT_RETENTION = timedelta(hours=24)
RECONNECT_MESSAGE = "Twitch login expired; reconnect your account"
SYNC_ERROR_MESSAGE = "Twitch inventory sync failed"


@dataclass
class ProgressResult:
    connected: bool
    campaign_count: int
    drop_count: int
    notified_count: int


class ProgressService:
    """Sync one user's Twitch drop inventory and notifications."""

    def __init__(
        self,
        session: AsyncSession,
        user_id: int,
        settings: Settings,
        provider: TwitchUserProvider,
        telegram: TelegramProvider,
    ) -> None:
        self.session = session
        self.user_id = user_id
        self.settings = settings
        self.provider = provider
        self.telegram = telegram
        self.accounts = TwitchAccountRepository(session)
        self.users = UserRepository(session)

    async def run(self) -> ProgressResult:
        account = await self.accounts.get_for_user(self.user_id)
        if account is None:
            return self._empty(connected=False)

        # A user already marked for reconnect stays skipped until they log in
        # again (which clears the flag on the account row).
        if account.reconnect_required:
            return self._empty(connected=False)

        user = await self.users.get(self.user_id)
        if user is None:
            return self._empty(connected=False)

        account = await self._ensure_token(account)
        client_id = account.client_id or self.settings.gql_client_id
        try:
            inventory = await self.provider.fetch_inventory(
                account.access_token, client_id
            )
        except NotConfiguredError:
            # Global provider misconfiguration is not a per-user reconnect.
            raise
        except ReconnectRequiredError as exc:
            await self._mark_reconnect()
            raise ReconnectRequiredError(RECONNECT_MESSAGE) from exc
        except ProviderError as exc:
            await self.accounts.mark_error(self.user_id, SYNC_ERROR_MESSAGE)
            await self.session.commit()
            raise ProviderError(SYNC_ERROR_MESSAGE) from exc

        campaigns = inventory.get("dropCampaignsInProgress") or []
        if not isinstance(campaigns, list):
            campaigns = []

        rows = parse_inventory(campaigns)
        await self._record_completions(rows, inventory)

        now = datetime.now(timezone.utc)
        repo = ProgressRepository(self.session, self.user_id)
        await repo.replace(rows)
        await repo.add_snapshots(rows)
        await repo.prune_snapshots(now - SNAPSHOT_RETENTION)
        await self.accounts.mark_synced(self.user_id)
        await self.session.commit()

        notified = await self._notify(user, rows)
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

    def _empty(self, *, connected: bool) -> ProgressResult:
        return ProgressResult(
            connected=connected,
            campaign_count=0,
            drop_count=0,
            notified_count=0,
        )

    async def _ensure_token(self, account: TwitchAccount) -> TwitchAccount:
        expires = account.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        if not account.access_token:
            await self._mark_reconnect()
            raise ReconnectRequiredError(RECONNECT_MESSAGE)

        # The implicit grant has no refresh token. An expired token can only be
        # replaced by signing in again.
        if expires is not None and expires <= datetime.now(timezone.utc):
            await self._mark_reconnect()
            raise ReconnectRequiredError(RECONNECT_MESSAGE)

        return account

    async def _mark_reconnect(self) -> None:
        await self.accounts.mark_reconnect(self.user_id, RECONNECT_MESSAGE)
        await self.session.commit()

    async def _record_completions(self, rows: list[dict], inventory: dict) -> None:
        """Persist campaigns whose rewards are all claimed.

        ``dropCampaignsInProgress`` drops a campaign after its final reward is
        claimed; ``earnedDropRewards`` still lists the claimed rewards, so it is
        used to detect completion even when the campaign is no longer in
        progress. A campaign is also completed when every in-progress drop is
        claimed.
        """
        earned = parse_earned_rewards(inventory)
        campaigns = await CampaignRepository(self.session).list()

        rows_by_campaign: dict[str, list[dict]] = {}
        for row in rows:
            campaign_id = str(row.get("campaign_gql_id") or "")
            if campaign_id:
                rows_by_campaign.setdefault(campaign_id, []).append(row)

        completed: list[dict] = []
        for campaign in campaigns:
            campaign_id = campaign_gql_id_from_external_id(campaign.external_id)
            if not campaign_id:
                continue

            claimed_rewards = len(earned.get(campaign_id, set()))
            campaign_rows = rows_by_campaign.get(campaign_id, [])
            all_rows_claimed = bool(campaign_rows) and all(
                row["is_claimed"] for row in campaign_rows
            )
            if (
                len(campaign.rewards) > 0
                and claimed_rewards >= len(campaign.rewards)
            ) or all_rows_claimed:
                completed.append(
                    {
                        "campaign_gql_id": campaign_id,
                        "campaign_name": campaign.name,
                        "game_name": campaign.game.name if campaign.game else "",
                    }
                )

        await CampaignCompletionRepository(
            self.session, self.user_id
        ).upsert_many(completed)

    async def _notify(self, user: User, rows: list[dict]) -> int:
        if not self.telegram.configured:
            return 0
        if not user.telegram_enabled or not (user.telegram_chat_id or "").strip():
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

        repo = NotificationRepository(self.session, self.user_id)
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
            await self.telegram.send(
                message, user.telegram_chat_id.strip()
            )
        except ProviderError as exc:
            logger.warning("Telegram notification failed: %s", exc)
            for key, _ in claimed:
                await repo.release(key)
            return 0

        return len(claimed)
