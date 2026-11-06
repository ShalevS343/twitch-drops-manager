from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.domain.schemas import WatchQueueItemOut
from app.services.watch_queue_service import build_watch_queue

router = APIRouter()


@router.get("/watch-queue", response_model=list[WatchQueueItemOut])
async def list_watch_queue(session: SessionDep) -> list[WatchQueueItemOut]:
    return await build_watch_queue(session)
