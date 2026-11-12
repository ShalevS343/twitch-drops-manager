import pytest
from starlette.requests import Request

from app.core.rate_limit import (
    SlidingWindowRateLimiter,
    client_ip,
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


def test_client_ip_uses_first_forwarded_for_value():
    request = _request({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    assert client_ip(request) == "203.0.113.9"


def test_client_ip_falls_back_to_the_socket_address():
    request = _request(client=("10.0.0.1", 1234))
    assert client_ip(request) == "10.0.0.1"


def test_client_ip_handles_a_missing_client():
    request = _request(client=None)
    assert client_ip(request) == "unknown"


@pytest.fixture(autouse=True)
def _reset_limiter():
    from app.core import rate_limit

    rate_limit.reset_auth_limiter()
    yield
    rate_limit.reset_auth_limiter()
