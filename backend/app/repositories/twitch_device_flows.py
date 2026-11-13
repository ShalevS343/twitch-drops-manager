from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import TwitchDeviceFlow


class TwitchDeviceFlowRepository:
    """Short-lived device authorization rows.

    Rows contain the secret Twitch ``device_code`` and must never be exposed or
    logged. All lookups use the opaque ``flow_id`` handed to the browser.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        flow_id: str,
        device_code: str,
        user_code: str,
        verification_uri: str,
        client_id: str,
        invite_code: str,
        current_user_id: int | None,
        interval_seconds: int,
        expires_at: datetime,
        status: str = "pending",
    ) -> TwitchDeviceFlow:
        flow = TwitchDeviceFlow(
            flow_id=flow_id,
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            client_id=client_id,
            invite_code=invite_code,
            current_user_id=current_user_id,
            interval_seconds=max(1, int(interval_seconds)),
            status=status,
            expires_at=expires_at,
        )
        self.session.add(flow)
        await self.session.flush()
        return flow

    async def get_by_flow_id(self, flow_id: str) -> TwitchDeviceFlow | None:
        result = await self.session.execute(
            select(TwitchDeviceFlow).where(TwitchDeviceFlow.flow_id == flow_id)
        )
        return result.scalar_one_or_none()

    async def set_status(self, flow_id: str, status: str) -> bool:
        flow = await self.get_by_flow_id(flow_id)
        if flow is None:
            return False
        flow.status = status
        await self.session.flush()
        return True

    async def delete(self, flow_id: str) -> None:
        await self.session.execute(
            delete(TwitchDeviceFlow).where(TwitchDeviceFlow.flow_id == flow_id)
        )
        await self.session.flush()

    async def delete_expired(self, now: datetime | None = None) -> int:
        cutoff = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            delete(TwitchDeviceFlow).where(TwitchDeviceFlow.expires_at <= cutoff)
        )
        await self.session.flush()
        return int(result.rowcount or 0)
