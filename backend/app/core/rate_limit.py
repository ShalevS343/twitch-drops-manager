from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from starlette.requests import Request

from app.core.config import get_settings


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

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def check(self, key: str) -> bool:
        now = self._clock()
        hits = self._prune(key, now)
        if len(hits) >= self.limit:
            return False
        hits.append(now)
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


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
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
