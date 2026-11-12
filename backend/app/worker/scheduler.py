import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.db import SessionLocal, engine, init_db
from app.core.logging import configure_logging
from app.repositories.user_sessions import UserSessionRepository
from app.repositories.users import UserRepository
from app.services.factory import (
    build_progress_service,
    build_scan_service,
    build_watch_focus_service,
    get_telegram_provider,
)
from app.worker.telegram_poller import TelegramPoller

logger = logging.getLogger(__name__)


async def run_scan(session_factory=None) -> None:
    factory = session_factory or SessionLocal
    async with factory() as session:
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

        try:
            await UserSessionRepository(session).delete_expired()
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Expired session cleanup failed")


async def run_progress(session_factory=None) -> None:
    factory = session_factory or SessionLocal
    async with factory() as session:
        user_ids = await UserRepository(session).list_active_ids_with_accounts()

    for user_id in user_ids:
        async with factory() as session:
            try:
                result = await build_progress_service(session, user_id).run()
                if result.connected:
                    logger.info(
                        "Progress sync for user %s: %d campaigns, %d drops, "
                        "%d notifications",
                        user_id,
                        result.campaign_count,
                        result.drop_count,
                        result.notified_count,
                    )
            except Exception:
                logger.exception("Progress sync failed for user %s", user_id)


async def run_watcher(session_factory=None) -> None:
    factory = session_factory or SessionLocal
    async with factory() as session:
        user_ids = await UserRepository(session).list_active_ids_with_focus()

    for user_id in user_ids:
        async with factory() as session:
            try:
                state = await build_watch_focus_service(session, user_id).reconcile()
                if state.enabled:
                    focus = state.focus
                    logger.info(
                        "Watcher reconcile for user %s: status=%s target=%s "
                        "campaign=%s reason=%s",
                        user_id,
                        state.status,
                        focus.user_login if focus else "-",
                        focus.campaign_id if focus else "-",
                        focus.reason if focus else "-",
                    )
            except Exception:
                logger.exception("Watcher reconcile failed for user %s", user_id)


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

    poller: TelegramPoller | None = None
    poller_task: asyncio.Task[None] | None = None
    if settings.telegram_bot_token:
        poller = TelegramPoller(get_telegram_provider(), SessionLocal)
        poller_task = asyncio.create_task(poller.run())
        logger.info("Telegram poller started")
    else:
        logger.info("Telegram poller disabled: bot token is not configured")

    await run_scan()
    await run_progress()
    await run_watcher()

    try:
        await asyncio.Event().wait()
    finally:
        if poller is not None:
            await poller.stop()
        if poller_task is not None:
            poller_task.cancel()
            await asyncio.gather(poller_task, return_exceptions=True)
        scheduler.shutdown(wait=False)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
