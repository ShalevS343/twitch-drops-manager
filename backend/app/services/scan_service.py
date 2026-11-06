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
            await campaign_repo.upsert_many(parsed)
            await campaign_repo.delete_stale({item["external_id"] for item in parsed})
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
        if not streams or not self.telegram.configured:
            return 0

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

        repo = NotificationRepository(self.session)
        claimed: list[tuple[dict[str, Any], list[str]]] = []

        for stream in streams:
            if scoped:
                campaign_names = [
                    name
                    for campaign_id, name in zip(
                        stream["campaign_ids"], stream["campaign_names"]
                    )
                    if campaign_gql_by_id.get(campaign_id) in active_campaign_ids
                ]
                if not campaign_names:
                    continue
            else:
                campaign_names = list(stream["campaign_names"])

            dedupe_key = f"{stream['user_login'].casefold()}:{stream['game_id']}"
            if await repo.claim(dedupe_key):
                claimed.append((stream, campaign_names))

        if not claimed:
            return 0

        noun = "stream" if len(claimed) == 1 else "streams"
        lines = [f"Twitch Drops: {len(claimed)} eligible {noun} live"]
        for stream, campaign_names in claimed[:10]:
            campaign_text = (
                f" ({', '.join(campaign_names)})" if campaign_names else ""
            )
            lines.append(
                f"• {stream['game_name']} — {stream['user_name']}: "
                f"{stream['title']}{campaign_text}"
            )
            lines.append(f"  {stream['url']}")

        extra = len(claimed) - 10
        if extra > 0:
            lines.append(f"…and {extra} more")

        try:
            await self.telegram.send("\n".join(lines))
        except ProviderError as exc:
            logger.warning("Telegram notification failed: %s", exc)
            for stream, _ in claimed:
                await repo.release(
                    f"{stream['user_login'].casefold()}:{stream['game_id']}"
                )
            return 0

        return len(claimed)
