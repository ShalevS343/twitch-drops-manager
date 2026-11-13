from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    compare_secrets,
)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _effective_scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip().lower()
    return request.url.scheme.lower()


def _origin_allowed(request: Request, origin: str) -> bool:
    settings = get_settings()
    origin = origin.rstrip("/")

    allowed = [item.rstrip("/") for item in settings.cors_origin_list]
    if settings.public_origin_value:
        allowed.append(settings.public_origin_value)
    if allowed:
        return origin in allowed

    host = request.headers.get("host") or request.url.netloc
    return origin == f"{_effective_scheme(request)}://{host}"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Require the double-submit CSRF pair and an expected Origin.

    Public auth endpoints that create a session are exempt; everything else
    under the API prefix must echo the CSRF cookie when a session cookie exists.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = get_settings()
        prefix = settings.api_prefix.rstrip("/")
        path = request.url.path
        is_api = path == prefix or path.startswith(f"{prefix}/")
        unsafe = request.method.upper() in UNSAFE_METHODS
        exempt = {
            f"{prefix}/auth/twitch/connect",
            f"{prefix}/auth/twitch/device/start",
        }

        if is_api and unsafe:
            origin = request.headers.get("origin")
            if origin and not _origin_allowed(request, origin):
                return JSONResponse(
                    {"detail": "Origin not allowed"}, status_code=403
                )

            # The public connect endpoint needs no CSRF pair (it creates the
            # session), but it still gets the Origin check above.
            if path not in exempt and request.cookies.get(SESSION_COOKIE):
                csrf_cookie = request.cookies.get(CSRF_COOKIE) or ""
                csrf_header = request.headers.get(CSRF_HEADER) or ""
                if (
                    not csrf_cookie
                    or not csrf_header
                    or not compare_secrets(csrf_cookie, csrf_header)
                ):
                    return JSONResponse(
                        {"detail": "CSRF token missing or invalid"},
                        status_code=403,
                    )

        return await call_next(request)


class NoStoreMiddleware(BaseHTTPMiddleware):
    """Keep authenticated API responses out of shared/browser caches."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        settings = get_settings()
        prefix = settings.api_prefix.rstrip("/")
        path = request.url.path
        is_api = path == prefix or path.startswith(f"{prefix}/")
        if is_api and request.cookies.get(SESSION_COOKIE):
            response.headers["Cache-Control"] = "no-store"
        return response
