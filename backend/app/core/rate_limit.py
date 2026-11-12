from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from starlette.requests import Request

from app.core.config import get_settings

PRUNE_EVERY_CHECKS = 256


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


def get_auth_limiter() -> SlidingWindowRateLimiter:
    global _limiter, _limiter_limit
    limit = max(1, int(get_settings().auth_rate_limit_per_minute))
    if _limiter is None or _limiter_limit != limit:
        _limiter = SlidingWindowRateLimiter(limit)
        _limiter_limit = limit
    return _limiter


def reset_auth_limiter() -> None:
    global _limiter, _limiter_limit
    _limiter = None
    _limiter_limit = None
