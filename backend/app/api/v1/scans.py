from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ScanServiceDep, SessionDep
from app.core.exceptions import NotConfiguredError, ProviderError
from app.core.security import require_api_token
from app.domain.schemas import ScanResultOut, ScanRunOut
from app.repositories.scans import ScanRunRepository

router = APIRouter()


@router.post(
    "/scans",
    response_model=ScanResultOut,
    dependencies=[Depends(require_api_token)],
)
async def trigger_scan(service: ScanServiceDep) -> ScanResultOut:
    try:
        result = await service.run()
    except NotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return ScanResultOut(
        ok=True,
        campaign_count=result.campaign_count,
        stream_count=result.stream_count,
        notified_count=result.notified_count,
    )


@router.get("/scans/latest", response_model=ScanRunOut)
async def latest_scan(session: SessionDep) -> ScanRunOut:
    run = await ScanRunRepository(session).latest()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No scans yet")
    return ScanRunOut.model_validate(run)
