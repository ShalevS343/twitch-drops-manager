from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_api_token(x_api_token: str | None = Header(default=None)) -> None:
    expected = get_settings().api_token
    if not expected:
        return
    if x_api_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )
