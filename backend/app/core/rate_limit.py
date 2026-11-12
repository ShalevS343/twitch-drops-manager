from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, status
from starlette.requests import Request

from app.core.config import get_settings

PRUNE_EVERY_CHECKS = 256
GLOBAL_AUTH_KEY = "all"

# Authenticated, side-effectful actions get their own per-user budget so one
# signed-in account cannot hammer expensive or externally visible endpoints.
# These are intentionally modest: the UI only needs a manual refresh/test
# occasionally, and a real user rarely changes these settings.
ACTION_LIMITS: dict[str, int] = {
    "progress.refresh": 2,
    "notifications.test": 3,
    "telegram.link": 3,
    "telegram.unlink": 3,
    "auth.me.update": 10,
}


class SlidingWindowRateLimiter:
    """In-process sliding-window limiter for auth attempts."""

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = window_seconds
        self._clock = clock or time.monotonic
        self._hits: dict[str, deque[float]] = {}
        self._checks = 0

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def _prune_all(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for key in list(self._hits):
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self._hits[key]

    def prune_expired(self) -> None:
        """Drop expired hits and keys that no longer have any activity."""
        self._prune_all(self._clock())

    def check(self, key: str) -> bool:
        now = self._clock()
        hits = self._prune(key, now)
        if len(hits) >= self.limit:
            return False

        hits.append(now)
        self._checks += 1
        if self._checks % PRUNE_EVERY_CHECKS == 0:
            self._prune_all(now)
        return True

    def retry_after(self, key: str) -> int:
        now = self._clock()
        hits = self._prune(key, now)
        if len(hits) < self.limit:
            return 0
        wait = self.window_seconds - (now - hits[0])
        return max(1, math.ceil(wait))

    def reset(self) -> None:
        self._hits.clear()
        self._checks = 0


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # The trusted reverse proxy appends the peer it saw, so the last hop is
        # not attacker-controlled like a client-supplied first value.
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


_limiter: SlidingWindowRateLimiter | None = None
_limiter_limit: int | None = None
_global_limiter: SlidingWindowRateLimiter | None = None
_global_limiter_limit: int | None = None
_action_limiters: dict[str, SlidingWindowRateLimiter] = {}


def get_auth_limiter() -> SlidingWindowRateLimiter:
    global _limiter, _limiter_limit
    limit = max(1, int(get_settings().auth_rate_limit_per_minute))
    if _limiter is None or _limiter_limit != limit:
        _limiter = SlidingWindowRateLimiter(limit)
        _limiter_limit = limit
    return _limiter


def get_auth_global_limiter() -> SlidingWindowRateLimiter:
    """Deployment-wide circuit breaker for auth attempts.

    The per-IP bucket is checked first, so one address can consume at most its
    own per-IP budget of this shared bucket before it is rejected. That keeps a
    single noisy/misconfigured client from blocking every other sign-in.
    """
    global _global_limiter, _global_limiter_limit
    limit = max(1, int(get_settings().auth_global_rate_limit_per_minute))
    if _global_limiter is None or _global_limiter_limit != limit:
        _global_limiter = SlidingWindowRateLimiter(limit)
        _global_limiter_limit = limit
    return _global_limiter


def check_auth_rate_limits(key: str) -> int:
    """Account for one auth attempt and return 0, or a Retry-After value.

    Per-IP is evaluated before the global bucket so a single client cannot
    exhaust the shared budget before its own limit applies.
    """
    ip_limiter = get_auth_limiter()
    if not ip_limiter.check(key):
        return ip_limiter.retry_after(key)

    global_limiter = get_auth_global_limiter()
    if not global_limiter.check(GLOBAL_AUTH_KEY):
        return global_limiter.retry_after(GLOBAL_AUTH_KEY)
    return 0


def get_action_limiter(action: str) -> SlidingWindowRateLimiter:
    try:
        limit = ACTION_LIMITS[action]
    except KeyError as exc:  # pragma: no cover - programming error
        raise ValueError(f"Unknown rate-limited action: {action}") from exc

    limiter = _action_limiters.get(action)
    if limiter is None or limiter.limit != limit:
        limiter = SlidingWindowRateLimiter(limit)
        _action_limiters[action] = limiter
    return limiter


def enforce_user_action_limit(action: str, user_id: int) -> None:
    """Raise ``429`` when one user exceeds an action budget."""
    limiter = get_action_limiter(action)
    key = str(user_id)
    if limiter.check(key):
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests; try again later",
        headers={"Retry-After": str(limiter.retry_after(key))},
    )


def reset_auth_limiter() -> None:
    global _limiter, _limiter_limit, _global_limiter, _global_limiter_limit
    _limiter = None
    _limiter_limit = None
    _global_limiter = None
    _global_limiter_limit = None


def reset_action_limiters() -> None:
    _action_limiters.clear()
