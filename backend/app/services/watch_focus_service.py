from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProviderError
from app.domain.models import WatchFocus, utcnow
from app.domain.schemas import (
    WatchCandidateOut,
    WatchFocusOut,
    WatchQueueItemOut,
    WatchStateOut,
)
from app.providers.telegram import TelegramProvider
from app.repositories.notifications import NotificationRepository
from app.repositories.progress import ProgressRepository
from app.repositories.watch_focus import WatchFocusRepository
from app.services.progress_metrics import drop_remaining_minutes
from app.services.watch_queue_service import (
    FocusCandidate,
    build_watch_queue,
    find_candidate,
)

logger = logging.getLogger(__name__)

MAX_WATCHERS = 1
CANDIDATE_LIMIT = 8


class WatchFocusError(ValueError):
    """A dispatch request cannot be satisfied from the current queue."""


def _candidate_out(candidate: FocusCandidate) -> WatchCandidateOut:
    return WatchCandidateOut(
        stream_id=candidate.stream.stream_id,
        user_login=candidate.stream.user_login,
        user_name=candidate.stream.user_name,
        stream_url=candidate.stream.url,
        stream_title=candidate.stream.title,
        game_name=candidate.stream.game_name,
        game_box_art_url=candidate.stream.game_box_art_url,
        viewers=candidate.stream.viewers,
        campaign_id=candidate.campaign.campaign_id,
        campaign_name=candidate.campaign.campaign_name,
        target_minutes=candidate.campaign.remaining_minutes,
        ends_at=candidate.campaign.ends_at,
    )


def _build_candidates(
    items: list[WatchQueueItemOut],
    *,
    exclude_stream_id: int | None = None,
) -> list[WatchCandidateOut]:
    candidates: list[WatchCandidateOut] = []
    for item in items:
        if exclude_stream_id is not None and item.stream_id == exclude_stream_id:
            continue

        campaign = next(
            (entry for entry in item.campaigns if entry.remaining_minutes > 0), None
        )
        if campaign is None:
            continue

        candidates.append(_candidate_out(FocusCandidate(stream=item, campaign=campaign)))
        if len(candidates) >= CANDIDATE_LIMIT:
            break

    return candidates


def _find_current(
    items: list[WatchQueueItemOut], row: WatchFocus
) -> FocusCandidate | None:
    """Resolve the stored focus after a scan replaced stream rows.

    ``streams`` rows are recreated by every scan, so the database id is not a
    stable identity. Match the channel + campaign first, then fall back to the
    stored stream id.
    """
    if row.user_login and row.campaign_id:
        for item in items:
            if item.user_login != row.user_login:
                continue
            for campaign in item.campaigns:
                if (
                    campaign.campaign_id == row.campaign_id
                    and campaign.remaining_minutes > 0
                ):
                    return FocusCandidate(stream=item, campaign=campaign)

    if row.stream_id is not None and row.campaign_id:
        return find_candidate(
            items, stream_id=row.stream_id, campaign_id=row.campaign_id
        )

    return None


def _clear_target(row: WatchFocus) -> None:
    row.stream_id = None
    row.user_login = ""
    row.user_name = ""
    row.stream_url = ""
    row.stream_title = ""
    row.game_name = ""
    row.game_box_art_url = ""
    row.campaign_id = ""
    row.campaign_name = ""
    row.target_minutes = 0
    row.ends_at = None
    row.focused_at = None


def _apply_target(row: WatchFocus, candidate: FocusCandidate, reason: str) -> None:
    moved = (
        row.user_login != candidate.stream.user_login
        or row.campaign_id != candidate.campaign.campaign_id
    )

    row.enabled = True
    row.status = "focused"
    row.reason = reason
    row.stream_id = candidate.stream.stream_id
    row.user_login = candidate.stream.user_login
    row.user_name = candidate.stream.user_name
    row.stream_url = candidate.stream.url
    row.stream_title = candidate.stream.title
    row.game_name = candidate.stream.game_name
    row.game_box_art_url = candidate.stream.game_box_art_url
    row.campaign_id = candidate.campaign.campaign_id
    row.campaign_name = candidate.campaign.campaign_name
    row.target_minutes = candidate.campaign.remaining_minutes
    row.ends_at = candidate.campaign.ends_at

    if moved or row.focused_at is None:
        row.focused_at = utcnow()


class WatchFocusService:
    """Manage the single focused watcher over the urgency-sorted queue.

    The watcher monitors one live stream/campaign target. It notifies when the
    target goes offline while the campaign is still open, and turns itself off
    (with a notification) when the campaign completes. It never controls
    playback.
    """

    def __init__(
        self,
        session: AsyncSession,
        telegram: TelegramProvider | None = None,
    ) -> None:
        self.session = session
        self.telegram = telegram
        self.repo = WatchFocusRepository(session)

    def _state(
        self, row: WatchFocus | None, items: list[WatchQueueItemOut]
    ) -> WatchStateOut:
        enabled = bool(row and row.enabled)
        status = "idle"
        focus: WatchFocusOut | None = None
        if enabled and row is not None:
            status = (
                row.status
                if row.status in {"focused", "offline", "waiting"}
                else "waiting"
            )
            if status in {"focused", "offline"} and row.campaign_id:
                focus = WatchFocusOut.model_validate(row)
            elif status in {"focused", "offline"}:
                status = "waiting"

        return WatchStateOut(
            enabled=enabled,
            status=status,
            reason=row.reason if row is not None else "idle",
            max_watchers=MAX_WATCHERS,
            auto_move=False,
            focus=focus,
            candidates=_build_candidates(
                items, exclude_stream_id=focus.stream_id if focus else None
            ),
            updated_at=row.updated_at if row is not None else None,
        )

    async def _notify_once(self, dedupe_key: str, message: str) -> bool:
        """Send once, returning True when delivered or no channel is configured."""
        if self.telegram is None or not self.telegram.configured:
            return True

        repo = NotificationRepository(self.session)
        if not await repo.claim(dedupe_key):
            return True

        try:
            await self.telegram.send(message)
        except ProviderError as exc:
            logger.warning("Watcher notification failed: %s", exc)
            await repo.release(dedupe_key)
            return False
        return True

    async def _campaign_remaining(self, campaign_id: str) -> int:
        rows = await ProgressRepository(self.session).list()
        return max(
            (
                drop_remaining_minutes(row)
                for row in rows
                if row.campaign_gql_id == campaign_id
            ),
            default=0,
        )

    async def get_state(self) -> WatchStateOut:
        row = await self.repo.get()
        items = await build_watch_queue(self.session)
        return self._state(row, items)

    async def set_enabled(self, enabled: bool) -> WatchStateOut:
        row = await self.repo.get_or_create()
        items = await build_watch_queue(self.session)

        if not enabled:
            row.enabled = False
            row.status = "idle"
            row.reason = "disabled"
            _clear_target(row)
            await self.session.commit()
            return self._state(row, items)

        row.enabled = True
        current = _find_current(items, row) if row.campaign_id else None
        if current is not None:
            _apply_target(row, current, row.reason or "manual")
        else:
            candidate = find_candidate(items)
            if candidate is not None:
                _apply_target(row, candidate, "auto")
            else:
                row.status = "waiting"
                row.reason = "waiting"
                _clear_target(row)

        await self.session.commit()
        return self._state(row, items)

    async def focus(
        self,
        *,
        stream_id: int | None = None,
        campaign_id: str | None = None,
        strategy: str = "manual",
    ) -> WatchStateOut:
        if strategy not in {"manual", "auto", "next"}:
            raise WatchFocusError(f"Unknown dispatch strategy: {strategy}")

        row = await self.repo.get()
        items = await build_watch_queue(self.session)

        if strategy == "manual":
            if stream_id is None or not campaign_id:
                raise WatchFocusError(
                    "Manual focus requires both stream_id and campaign_id."
                )
            candidate = find_candidate(
                items, stream_id=stream_id, campaign_id=campaign_id
            )
            if candidate is None:
                raise WatchFocusError(
                    "That live stream/campaign is not in the queue or has no "
                    "watch time left."
                )
            row = row or await self.repo.get_or_create()
            _apply_target(row, candidate, "manual")
            # A manual focus starts a new monitoring session, so a later
            # offline event can notify again.
            row.focused_at = utcnow()

        elif strategy == "next":
            row = row or await self.repo.get_or_create()
            candidate = find_candidate(
                items,
                campaign_id=campaign_id,
                exclude_stream_id=row.stream_id,
            )
            if candidate is not None:
                _apply_target(row, candidate, "next")
            else:
                current = _find_current(items, row) if row.campaign_id else None
                if current is not None:
                    _apply_target(row, current, row.reason or "manual")
                    row.reason = "next-unavailable"
                else:
                    row.status = "waiting"
                    row.reason = "waiting"
                    _clear_target(row)

        else:  # auto
            row = row or await self.repo.get_or_create()
            candidate = find_candidate(items, campaign_id=campaign_id)
            if candidate is not None:
                _apply_target(row, candidate, "auto")
            else:
                current = _find_current(items, row) if row.campaign_id else None
                if current is not None:
                    _apply_target(row, current, row.reason or "manual")
                    row.reason = "auto-unavailable"
                else:
                    row.status = "waiting"
                    row.reason = "waiting"
                    _clear_target(row)

        await self.session.commit()
        return self._state(row, items)

    async def reconcile(self) -> WatchStateOut:
        """Monitor the focused target and react to offline/completed campaigns.

        - Campaign complete: notify once, then turn focused mode off.
        - Live gone but campaign still open: notify once per online session and
          keep the target in ``offline`` state so the user can pick another live.
        - No target yet: select the next candidate when one appears.
        """
        row = await self.repo.get()
        items = await build_watch_queue(self.session)
        if row is None or not row.enabled:
            return self._state(row, items)

        if not row.campaign_id:
            candidate = find_candidate(items)
            if candidate is not None:
                _apply_target(row, candidate, "auto")
            else:
                row.status = "waiting"
                row.reason = "waiting"
                _clear_target(row)
            await self.session.commit()
            return self._state(row, items)

        current = _find_current(items, row)
        if current is not None:
            was_offline = row.status == "offline"
            _apply_target(
                row,
                current,
                "live" if was_offline else (row.reason or "manual"),
            )
            if was_offline:
                # New online session: allow the next offline event to notify.
                row.focused_at = utcnow()
                row.reason = "live"
            await self.session.commit()
            return self._state(row, items)

        remaining = await self._campaign_remaining(row.campaign_id)
        if remaining <= 0:
            delivered = await self._notify_once(
                f"watch-complete:{row.campaign_id}",
                (
                    "Twitch Drops: campaign complete.\n"
                    f"{row.campaign_name} ({row.game_name}) has no watch time "
                    "left.\n"
                    "Focus mode has been turned off."
                ),
            )
            if delivered:
                row.enabled = False
                row.status = "idle"
                row.reason = "completed"
                _clear_target(row)
            else:
                row.status = "waiting"
                row.reason = "completion-pending"
            await self.session.commit()
            return self._state(row, items)

        marker = row.focused_at.isoformat() if row.focused_at else "unknown"
        delivered = await self._notify_once(
            f"watch-offline:{row.campaign_id}:{row.user_login}:{marker}",
            (
                f"Twitch Drops: {row.user_name or row.user_login} is no longer "
                "live.\n"
                f"{row.campaign_name} ({row.game_name}) still has "
                f"{remaining} min left.\n"
                "Pick another live stream in the watch queue."
            ),
        )
        row.status = "offline"
        row.reason = "offline" if delivered else "offline-pending"
        row.target_minutes = remaining
        await self.session.commit()
        return self._state(row, items)
