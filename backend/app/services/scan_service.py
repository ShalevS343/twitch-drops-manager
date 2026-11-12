import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    NotConfiguredError,
    ProviderError,
    describe_exception,
    safe_scan_error,
)
from app.domain.models import Campaign, Game, ScanRun
from app.domain.parsing import (
    campaign_matches_stream,
    campaigns_of,
    game_name,
    game_twitch_id,
    parse_campaign,
)
from app.providers.sunkwi import SunkwiProvider
from app.providers.telegram import TelegramProvider
from app.providers.twitch import TwitchProvider
from app.repositories.campaign_starts import CampaignStartRepository
from app.repositories.campaigns import CampaignRepository
from app.repositories.games import GameRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.streams import StreamRepository
from app.repositories.user_games import UserGameRepository
from app.repositories.user_sessions import UserSessionRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScanResult:
    campaign_count: int
    stream_count: int
    notified_count: int


class ScanService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        sunkwi: SunkwiProvider,
        twitch: TwitchProvider,
        telegram: TelegramProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.sunkwi = sunkwi
        self.twitch = twitch
        self.telegram = telegram

    async def run(self) -> ScanResult:
        started_at = utcnow()

        try:
            await UserSessionRepository(self.session).delete_expired()
            payload = await self.sunkwi.fetch_games()
            games = payload.get("games", []) if isinstance(payload, dict) else []

            await self._sync_games(games)

            game_repo = GameRepository(self.session)
            selected_names = await UserGameRepository(
                self.session
            ).list_union_names()
            games_by_name = {
                game.name.casefold(): game for game in await game_repo.list()
            }

            parsed = self._parse_campaigns(games, games_by_name)
            campaign_repo = CampaignRepository(self.session)
            existing_status = await campaign_repo.statuses_by_external_ids(
                {item["external_id"] for item in parsed}
            )
            await campaign_repo.upsert_many(parsed)
            await campaign_repo.delete_stale({item["external_id"] for item in parsed})

            started = self._started_campaigns(parsed, existing_status)
            if self.telegram.configured:
                targets = await UserGameRepository(self.session).telegram_targets()
                for user_id, names in targets.items():
                    tracked = {name.casefold() for name in names}
                    items = [
                        item
                        for item in started
                        if self._campaign_game_name(item).casefold() in tracked
                    ]
                    await CampaignStartRepository(
                        self.session, user_id
                    ).add_pending(items)
            await CampaignStartRepository.delete_all_orphans(self.session)
            await self.session.commit()

            active = await campaign_repo.list_active_for_games(selected_names)
            streams = await self._discover_streams(active)
            await StreamRepository(self.session).replace(streams)
            await self.session.commit()

            notified = await self._notify()
            await self.session.commit()

            self.session.add(
                ScanRun(
                    started_at=started_at,
                    finished_at=utcnow(),
                    ok=True,
                    campaign_count=len(parsed),
                    stream_count=len(streams),
                )
            )
            await self.session.commit()

            logger.info(
                "Scan complete: %d campaigns, %d streams, %d notifications",
                len(parsed),
                len(streams),
                notified,
            )
            return ScanResult(
                campaign_count=len(parsed),
                stream_count=len(streams),
                notified_count=notified,
            )
        except Exception as exc:
            await self.session.rollback()
            safe_error = safe_scan_error(exc)
            self.session.add(
                ScanRun(
                    started_at=started_at,
                    finished_at=utcnow(),
                    ok=False,
                    error=safe_error,
                )
            )
            await self.session.commit()
            # Exception text/tracebacks can contain request URLs, bodies, and
            # tokens. Log only the type plus the same fixed message stored in
            # scan_runs.error.
            logger.error("Scan failed (%s)", describe_exception(exc))
            raise

    async def _sync_games(self, games: list[Any]) -> None:
        repo = GameRepository(self.session)

        for game in games:
            if not isinstance(game, dict):
                continue
            name = game_name(game)
            if not name:
                continue
            await repo.upsert(
                name,
                str(game.get("gameBoxArtURL") or ""),
                game_twitch_id(game),
            )

        await self.session.flush()

    def _parse_campaigns(
        self, games: list[Any], games_by_name: dict[str, Game]
    ) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []

        for game in games:
            if not isinstance(game, dict):
                continue
            name = game_name(game)
            db_game = games_by_name.get(name.casefold())
            if db_game is None:
                continue
            for campaign in campaigns_of(game):
                parsed.append(parse_campaign(campaign, name, db_game.id))

        return parsed

    @staticmethod
    def _campaign_game_name(item: dict[str, Any]) -> str:
        return str(item["external_id"]).rsplit(":", 1)[0]

    @classmethod
    def _started_campaigns(
        cls,
        parsed: list[dict[str, Any]],
        existing_status: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Campaigns that became ACTIVE since the last scan."""
        started: list[dict[str, Any]] = []

        for item in parsed:
            if item["status"] != "ACTIVE":
                continue
            if existing_status.get(item["external_id"]) == "ACTIVE":
                continue
            started.append(item)

        return started

    async def _discover_streams(self, campaigns: list[Campaign]) -> list[dict[str, Any]]:
        by_game: dict[str, list[Campaign]] = {}
        for campaign in campaigns:
            if campaign.game and campaign.game.twitch_game_id:
                by_game.setdefault(campaign.game.twitch_game_id, []).append(campaign)

        if not by_game:
            return []
        if not self.twitch.ready:
            raise NotConfiguredError("Twitch API credentials not configured")

        found: dict[tuple[str, int], dict[str, Any]] = {}

        for twitch_game_id, game_campaigns in by_game.items():
            game = game_campaigns[0].game
            streams = await self.twitch.get_streams(twitch_game_id)

            for stream in streams:
                user_login = str(stream.get("user_login") or "")
                if not user_login:
                    continue

                matching = [
                    campaign
                    for campaign in game_campaigns
                    if campaign_matches_stream(campaign.allow, user_login)
                ]
                if not matching:
                    continue

                key = (user_login.casefold(), game.id)
                found[key] = {
                    "game_id": game.id,
                    "game_name": game.name,
                    "user_login": user_login,
                    "user_name": str(stream.get("user_name") or user_login),
                    "title": str(stream.get("title") or ""),
                    "viewers": int(stream.get("viewer_count") or 0),
                    "language": str(stream.get("language") or ""),
                    "started_at": stream.get("started_at"),
                    "url": f"https://www.twitch.tv/{user_login}",
                    "campaign_ids": [campaign.id for campaign in matching],
                    "campaign_names": [campaign.name for campaign in matching],
                    "eligibility": "Potential campaign match; verify on Twitch",
                }

        return list(found.values())

    async def _notify(self) -> int:
        # Telegram notifications are campaign-start (and focused-watcher) only.
        # New live streams are intentionally not sent.
        if not self.telegram.configured:
            return 0

        users = await UserRepository(self.session).list_active_with_telegram()
        total = 0

        for user in users:
            start_repo = CampaignStartRepository(self.session, user.id)
            pending_starts = await start_repo.pending()
            if not pending_starts:
                continue

            repo = NotificationRepository(self.session, user.id)
            claimed: list[tuple[Campaign, str]] = []
            already_notified: set[str] = set()
            for start, campaign in pending_starts:
                dedupe_key = f"campaign-started:{campaign.external_id}"
                if await repo.claim(dedupe_key):
                    claimed.append((campaign, dedupe_key))
                else:
                    already_notified.add(start.external_id)
            if already_notified:
                await start_repo.delete(already_notified)
                await self.session.commit()
            if not claimed:
                continue

            lines = ["Twitch Drops update", "New campaign:"]
            for campaign, _ in claimed:
                game = campaign.external_id.rsplit(":", 1)[0]
                line = f"• {game} — {campaign.name}"
                if campaign.ends_at:
                    line += f" (ends {campaign.ends_at})"
                lines.append(line)
                if campaign.details_url:
                    lines.append(f"  {campaign.details_url}")

            try:
                await self.telegram.send(
                    "\n".join(lines), user.telegram_chat_id.strip()
                )
            except ProviderError as exc:
                logger.warning(
                    "Telegram notification failed (%s)",
                    describe_exception(exc),
                )
                for _, dedupe_key in claimed:
                    await repo.release(dedupe_key)
                await self.session.commit()
                continue

            await start_repo.delete(
                {campaign.external_id for campaign, _ in claimed}
            )
            # Persist each user's claim/deletion immediately so a later user's
            # failure cannot cause this digest to be sent again on retry.
            await self.session.commit()
            total += len(claimed)

        return total
