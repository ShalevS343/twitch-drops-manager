from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import WatchFocus, utcnow
from app.domain.schemas import (
    WatchCandidateOut,
    WatchFocusOut,
    WatchQueueItemOut,
    WatchStateOut,
)
from app.repositories.watch_focus import WatchFocusRepository
from app.services.watch_queue_service import (
    FocusCandidate,
    build_watch_queue,
    find_candidate,
)

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

    This is a focus pointer only. It never controls playback, sends watch
    heartbeats, or simulates viewing.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WatchFocusRepository(session)

    def _state(
        self, row: WatchFocus | None, items: list[WatchQueueItemOut]
    ) -> WatchStateOut:
        enabled = bool(row and row.enabled)
        status = "idle"
        focus: WatchFocusOut | None = None
        if enabled and row is not None:
            status = row.status if row.status in {"focused", "waiting"} else "waiting"
            if status == "focused" and row.campaign_id:
                focus = WatchFocusOut.model_validate(row)
            elif status == "focused":
                status = "waiting"

        return WatchStateOut(
            enabled=enabled,
            status=status,
            max_watchers=MAX_WATCHERS,
            auto_move=True,
            focus=focus,
            candidates=_build_candidates(
                items, exclude_stream_id=focus.stream_id if focus else None
            ),
            updated_at=row.updated_at if row is not None else None,
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

        elif strategy == "next":
            row = row or await self.repo.get_or_create()
            candidate = find_candidate(
                items,
                campaign_id=campaign_id,
                exclude_stream_id=row.stream_id,
            )
            if candidate is not None:
                _apply_target(row, candidate, "auto-move")
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
        """Advance the focus when its live stream leaves the queue.

        The worker calls this on an interval. When the focused channel goes
        offline, ends, or its campaign runs out of watch time, the watcher moves
        to the next dispatchable live stream. If nothing is available it waits.
        """
        row = await self.repo.get()
        items = await build_watch_queue(self.session)
        if row is None or not row.enabled:
            return self._state(row, items)

        current = _find_current(items, row) if row.campaign_id else None
        if current is not None:
            _apply_target(row, current, row.reason or "manual")
        else:
            candidate = find_candidate(items, exclude_stream_id=row.stream_id)
            if candidate is not None:
                _apply_target(row, candidate, "auto-move")
            else:
                row.status = "waiting"
                row.reason = "waiting"
                _clear_target(row)

        await self.session.commit()
        return self._state(row, items)
