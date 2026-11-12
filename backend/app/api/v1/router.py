from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    campaigns,
    games,
    health,
    notifications,
    progress,
    scans,
    status,
    streams,
    telegram,
    watch_queue,
    watcher,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(telegram.router, tags=["telegram"])
api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(status.router, tags=["status"])
api_router.include_router(games.router, tags=["games"])
api_router.include_router(campaigns.router, tags=["campaigns"])
api_router.include_router(streams.router, tags=["streams"])
api_router.include_router(scans.router, tags=["scans"])
api_router.include_router(notifications.router, tags=["notifications"])
api_router.include_router(progress.router, tags=["progress"])
api_router.include_router(watch_queue.router, tags=["watch-queue"])
api_router.include_router(watcher.router, tags=["watcher"])
