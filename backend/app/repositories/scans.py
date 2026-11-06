from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import ScanRun


class ScanRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest(self) -> ScanRun | None:
        result = await self.session.execute(
            select(ScanRun).order_by(ScanRun.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()
