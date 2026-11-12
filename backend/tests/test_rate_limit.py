import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.rate_limit import (
    GLOBAL_AUTH_KEY,
    SlidingWindowRateLimiter,
    check_auth_rate_limits,
    client_ip,
    enforce_user_action_limit,
    get_action_limiter,
)


def test_sliding_window_allows_up_to_the_limit_then_rejects():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(3, window_seconds=60, clock=lambda: now[0])

    assert limiter.check("1.2.3.4") is True
    assert limiter.check("1.2.3.4") is True
    assert limiter.check("1.2.3.4") is True
    assert limiter.check("1.2.3.4") is False
    assert limiter.retry_after("1.2.3.4") == 60

    now[0] += 30
    assert limiter.retry_after("1.2.3.4") == 30

    now[0] += 30
    assert limiter.check("1.2.3.4") is True


def test_rate_limit_is_keyed_per_client():
    limiter = SlidingWindowRateLimiter(1, window_seconds=60, clock=lambda: 0.0)
    assert limiter.check("first") is True
    assert limiter.check("first") is False
    assert limiter.check("second") is True


def test_retry_after_is_zero_when_under_the_limit():
    limiter = SlidingWindowRateLimiter(2, window_seconds=60, clock=lambda: 0.0)
    assert limiter.retry_after("client") == 0
    limiter.check("client")
    assert limiter.retry_after("client") == 0


def _request(headers: dict[str, str] | None = None, client=("10.0.0.1", 1234)) -> Request:
    raw_headers = [
        (key.lower().encode(), value.encode())
        for key, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/twitch/connect",
        "raw_path": b"/api/v1/auth/twitch/connect",
        "query_string": b"",
        "headers": raw_headers,
        "client": client,
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_client_ip_uses_the_last_forwarded_for_hop():
    request = _request({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    assert client_ip(request) == "10.0.0.1"


def test_client_ip_ignores_a_spoofed_first_forwarded_for_value():
    request = _request(
        {"X-Forwarded-For": "198.51.100.7, 203.0.113.9, 10.0.0.1"}
    )
    assert client_ip(request) == "10.0.0.1"


def test_prune_expired_removes_idle_keys():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(2, window_seconds=60, clock=lambda: now[0])
    limiter.check("expired")
    limiter.check("active")
    now[0] += 61

    limiter.prune_expired()

    assert "expired" not in limiter._hits
    assert "active" not in limiter._hits
    assert limiter._hits == {}


def test_prune_expired_keeps_keys_inside_the_window():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(2, window_seconds=60, clock=lambda: now[0])
    limiter.check("recent")
    now[0] += 30

    limiter.prune_expired()

    assert "recent" in limiter._hits


def test_client_ip_falls_back_to_the_socket_address():
    request = _request(client=("10.0.0.1", 1234))
    assert client_ip(request) == "10.0.0.1"


def test_client_ip_handles_a_missing_client():
    request = _request(client=None)
    assert client_ip(request) == "unknown"


def test_action_limiter_budgets_are_separate_per_user_and_action():
    progress = get_action_limiter("progress.refresh")
    assert progress.limit == 2
    assert progress.check("1") is True
    assert progress.check("1") is True
    assert progress.check("1") is False
    # A different user has an independent budget.
    assert progress.check("2") is True

    notifications = get_action_limiter("notifications.test")
    assert notifications.limit == 3
    assert notifications is not progress
    assert notifications.check("1") is True


def test_enforce_user_action_limit_raises_429_with_retry_after():
    enforce_user_action_limit("progress.refresh", 7)
    enforce_user_action_limit("progress.refresh", 7)

    with pytest.raises(HTTPException) as excinfo:
        enforce_user_action_limit("progress.refresh", 7)

    assert excinfo.value.status_code == 429
    assert int(excinfo.value.headers["Retry-After"]) >= 1
    # Another user is unaffected.
    enforce_user_action_limit("progress.refresh", 8)


def test_global_auth_limiter_caps_shared_attempts(monkeypatch):
    from app.core import rate_limit

    per_ip = SlidingWindowRateLimiter(100, clock=lambda: 0.0)
    global_limiter = SlidingWindowRateLimiter(2, clock=lambda: 0.0)
    monkeypatch.setattr(rate_limit, "get_auth_limiter", lambda: per_ip)
    monkeypatch.setattr(
        rate_limit, "get_auth_global_limiter", lambda: global_limiter
    )

    assert check_auth_rate_limits("10.0.0.1") == 0
    assert check_auth_rate_limits("10.0.0.2") == 0
    assert check_auth_rate_limits("10.0.0.3") > 0


def test_one_ip_cannot_exhaust_the_global_bucket_before_its_own_limit(
    monkeypatch,
):
    from app.core import rate_limit

    per_ip = SlidingWindowRateLimiter(2, clock=lambda: 0.0)
    global_limiter = SlidingWindowRateLimiter(3, clock=lambda: 0.0)
    monkeypatch.setattr(rate_limit, "get_auth_limiter", lambda: per_ip)
    monkeypatch.setattr(
        rate_limit, "get_auth_global_limiter", lambda: global_limiter
    )

    assert check_auth_rate_limits("10.0.0.1") == 0
    assert check_auth_rate_limits("10.0.0.1") == 0
    # The same IP is now rejected by its per-IP bucket...
    assert check_auth_rate_limits("10.0.0.1") > 0
    # ...so it consumed only two of the three shared slots.
    assert len(global_limiter._hits[GLOBAL_AUTH_KEY]) == 2

    assert check_auth_rate_limits("10.0.0.2") == 0
    assert check_auth_rate_limits("10.0.0.3") > 0


@pytest.fixture(autouse=True)
def _reset_limiter():
    from app.core import rate_limit

    rate_limit.reset_auth_limiter()
    yield
    rate_limit.reset_auth_limiter()
