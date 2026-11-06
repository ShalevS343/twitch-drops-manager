import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotConfiguredError, ProviderError
from app.domain.models import Campaign, Game, ScanRun
from app.domain.parsing import (
    campaign_gql_id_from_external_id,
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
from app.repositories.progress import ProgressRepository
from app.repositories.streams import StreamRepository

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
            payload = await self.sunkwi.fetch_games()
            games = payload.get("games", []) if isinstance(payload, dict) else []

            await self._sync_games(games)

            game_repo = GameRepository(self.session)
            selected = await game_repo.list_selected()
            selected_names = {game.name for game in selected}
            games_by_name = {game.name.casefold(): game for game in await game_repo.list()}

            parsed = self._parse_campaigns(games, games_by_name)
            campaign_repo = CampaignRepository(self.session)
            existing_status = await campaign_repo.statuses_by_external_ids(
                {item["external_id"] for item in parsed}
            )
            await campaign_repo.upsert_many(parsed)
            await campaign_repo.delete_stale({item["external_id"] for item in parsed})

            start_repo = CampaignStartRepository(self.session)
            await start_repo.add_pending(
                self._started_campaigns(parsed, existing_status, selected_names)
            )
            await start_repo.delete_orphans()
            await self.session.commit()

            active = await campaign_repo.list_active_for_games(selected_names)
            streams = await self._discover_streams(active)
            await StreamRepository(self.session).replace(streams)
            await self.session.commit()

            notified = await self._notify(streams)
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
            self.session.add(
                ScanRun(
                    started_at=started_at,
                    finished_at=utcnow(),
                    ok=False,
                    error=str(exc),
                )
            )
            await self.session.commit()
            logger.exception("Scan failed")
            raise

    async def _sync_games(self, games: list[Any]) -> None:
        repo = GameRepository(self.session)
        had_games = await repo.count() > 0

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

        if not had_games and self.settings.default_game_list:
            await repo.select_defaults(self.settings.default_game_list)

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
    def _started_campaigns(
        parsed: list[dict[str, Any]],
        existing_status: dict[str, str],
        selected_names: set[str],
    ) -> list[dict[str, Any]]:
        """Campaigns that became ACTIVE for a tracked game since the last scan."""
        selected = {name.casefold() for name in selected_names}
        started: list[dict[str, Any]] = []

        for item in parsed:
            if item["status"] != "ACTIVE":
                continue
            if existing_status.get(item["external_id"]) == "ACTIVE":
                continue

            game = item["external_id"].rsplit(":", 1)[0]
            if game.casefold() not in selected:
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

    async def _notify(self, streams: list[dict[str, Any]]) -> int:
        start_repo = CampaignStartRepository(self.session)
        pending_starts = await start_repo.pending()

        # Stream alerts are tied to a campaign-start event: without a new
        # campaign there is no stream digest, even if new streams appeared.
        if not pending_starts:
            return 0
        if not self.telegram.configured:
            return 0

        repo = NotificationRepository(self.session)

        claimed_starts: list[tuple[Campaign, str]] = []
        already_notified: set[str] = set()
        for start, campaign in pending_starts:
            dedupe_key = f"campaign-started:{campaign.external_id}"
            if await repo.claim(dedupe_key):
                claimed_starts.append((campaign, dedupe_key))
            else:
                already_notified.add(start.external_id)
        if already_notified:
            await start_repo.delete(already_notified)

        # Nothing new to announce (the starts were already delivered); do not
        # send a standalone stream digest.
        if not claimed_starts:
            return 0

        started_game_ids = {campaign.game_id for campaign, _ in claimed_starts}
        started_campaign_ids = {campaign.id for campaign, _ in claimed_starts}
        start_key_by_game: dict[int, str] = {}
        for campaign, _ in claimed_starts:
            current = start_key_by_game.get(campaign.game_id)
            if current is None or campaign.external_id < current:
                start_key_by_game[campaign.game_id] = campaign.external_id

        claimed_streams: list[tuple[dict[str, Any], list[str], str]] = []
        if streams:
            progress_rows = await ProgressRepository(self.session).list()
            scoped = bool(progress_rows)
            active_campaign_ids = {
                row.campaign_gql_id for row in progress_rows if row.campaign_gql_id
            }

            campaign_gql_by_id: dict[int, str] = {}
            if scoped:
                campaign_ids = {
                    campaign_id
                    for stream in streams
                    for campaign_id in stream["campaign_ids"]
                }
                campaigns = await CampaignRepository(self.session).by_ids(campaign_ids)
                campaign_gql_by_id = {
                    campaign.id: campaign_gql_id_from_external_id(campaign.external_id)
                    for campaign in campaigns
                }

            for stream in streams:
                if stream["game_id"] not in started_game_ids:
                    continue

                if scoped:
                    campaign_names = [
                        name
                        for campaign_id, name in zip(
                            stream["campaign_ids"], stream["campaign_names"]
                        )
                        if campaign_gql_by_id.get(campaign_id) in active_campaign_ids
                    ]
                    # A just-started campaign may not be in drop_progress yet.
                    campaign_names.extend(
                        name
                        for campaign_id, name in zip(
                            stream["campaign_ids"], stream["campaign_names"]
                        )
                        if campaign_id in started_campaign_ids
                    )
                    campaign_names = list(dict.fromkeys(campaign_names))
                    if not campaign_names:
                        continue
                else:
                    campaign_names = list(stream["campaign_names"])

                # Key by the campaign-start event so a later campaign for the
                # same game can notify the same channel again.
                start_key = start_key_by_game[stream["game_id"]]
                dedupe_key = (
                    f"stream-alert:{start_key}:"
                    f"{stream['user_login'].casefold()}:{stream['game_id']}"
                )
                if await repo.claim(dedupe_key):
                    claimed_streams.append((stream, campaign_names, dedupe_key))

        lines = ["Twitch Drops update"]

        lines.append("New campaign:")
        for campaign, _ in claimed_starts:
            game = campaign.external_id.rsplit(":", 1)[0]
            line = f"• {game} — {campaign.name}"
            if campaign.ends_at:
                line += f" (ends {campaign.ends_at})"
            lines.append(line)
            if campaign.details_url:
                lines.append(f"  {campaign.details_url}")

        if claimed_streams:
            lines.append("")
            noun = "stream" if len(claimed_streams) == 1 else "streams"
            lines.append(f"Live now ({len(claimed_streams)} {noun}):")
            for stream, campaign_names, _ in claimed_streams[:10]:
                campaign_text = (
                    f" ({', '.join(campaign_names)})" if campaign_names else ""
                )
                lines.append(
                    f"• {stream['game_name']} — {stream['user_name']}: "
                    f"{stream['title']}{campaign_text}"
                )
                lines.append(f"  {stream['url']}")

            extra = len(claimed_streams) - 10
            if extra > 0:
                lines.append(f"…and {extra} more")

        try:
            await self.telegram.send("\n".join(lines))
        except ProviderError as exc:
            logger.warning("Telegram notification failed: %s", exc)
            for _, dedupe_key in claimed_starts:
                await repo.release(dedupe_key)
            for _, _, dedupe_key in claimed_streams:
                await repo.release(dedupe_key)
            return 0

        await start_repo.delete(
            {campaign.external_id for campaign, _ in claimed_starts}
        )

        return len(claimed_starts) + len(claimed_streams)
