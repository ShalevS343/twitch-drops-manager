import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.db import SessionLocal, engine, init_db
from app.core.logging import configure_logging
from app.services.factory import build_scan_service

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
    scheduler.start()
    logger.info("Scan worker started (interval=%ss)", interval)

    await run_scan()

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
