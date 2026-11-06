import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.db import SessionLocal, engine, init_db
from app.core.logging import configure_logging
from app.services.factory import (
    build_progress_service,
    build_scan_service,
    build_watch_focus_service,
)

logger = logging.getLogger(__name__)


async def run_scan() -> None:
    async with SessionLocal() as session:
        service = build_scan_service(session)
        try:
            result = await service.run()
            logger.info(
                "Scheduled scan: %d campaigns, %d streams, %d notifications",
                result.campaign_count,
                result.stream_count,
                result.notified_count,
            )
        except Exception:
            logger.exception("Scheduled scan failed")


async def run_progress() -> None:
    async with SessionLocal() as session:
        try:
            result = await build_progress_service(session).run()
            if result.connected:
                logger.info(
                    "Progress sync: %d campaigns, %d drops, %d notifications",
                    result.campaign_count,
                    result.drop_count,
                    result.notified_count,
                )
        except Exception:
            logger.exception("Progress sync failed")


async def run_watcher() -> None:
    async with SessionLocal() as session:
        try:
            state = await build_watch_focus_service(session).reconcile()
            if state.enabled:
                focus = state.focus
                logger.info(
                    "Watcher reconcile: status=%s target=%s campaign=%s reason=%s",
                    state.status,
                    focus.user_login if focus else "-",
                    focus.campaign_id if focus else "-",
                    focus.reason if focus else "-",
                )
        except Exception:
            logger.exception("Watcher reconcile failed")


async def main() -> None:
    configure_logging()
    await init_db()

    settings = get_settings()
    interval = settings.poll_interval_seconds

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scan,
        "interval",
        seconds=interval,
        id="scan",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_progress,
        "interval",
        seconds=settings.progress_interval_seconds,
        id="progress",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_watcher,
        "interval",
        seconds=settings.watcher_interval_seconds,
        id="watcher",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scan worker started (scan=%ss, progress=%ss, watcher=%ss)",
        interval,
        settings.progress_interval_seconds,
        settings.watcher_interval_seconds,
    )

    await run_scan()
    await run_progress()
    await run_watcher()

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
