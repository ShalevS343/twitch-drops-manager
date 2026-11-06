from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import SessionDep
from app.core.security import require_api_token
from app.domain.schemas import WatchFocusIn, WatchStateOut, WatchToggleIn
from app.services.factory import build_watch_focus_service
from app.services.watch_focus_service import WatchFocusError

router = APIRouter()


@router.get("/watcher", response_model=WatchStateOut)
async def get_watcher(session: SessionDep) -> WatchStateOut:
    return await build_watch_focus_service(session).get_state()


@router.patch(
    "/watcher",
    response_model=WatchStateOut,
    dependencies=[Depends(require_api_token)],
)
async def set_watcher(
    payload: WatchToggleIn, session: SessionDep
) -> WatchStateOut:
    return await build_watch_focus_service(session).set_enabled(payload.enabled)


@router.post(
    "/watcher/focus",
    response_model=WatchStateOut,
    dependencies=[Depends(require_api_token)],
)
async def focus_watcher(
    payload: WatchFocusIn, session: SessionDep
) -> WatchStateOut:
    try:
        return await build_watch_focus_service(session).focus(
            stream_id=payload.stream_id,
            campaign_id=payload.campaign_id,
            strategy=payload.strategy,
        )
    except WatchFocusError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/watcher",
    response_model=WatchStateOut,
    dependencies=[Depends(require_api_token)],
)
async def stop_watcher(session: SessionDep) -> WatchStateOut:
    return await build_watch_focus_service(session).set_enabled(False)
