"""Shared test fixtures."""

from __future__ import annotations

import pytest

from app.core import rate_limit


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Keep in-process limiter state from leaking between tests."""
    rate_limit.reset_auth_limiter()
    rate_limit.reset_action_limiters()
    yield
    rate_limit.reset_auth_limiter()
    rate_limit.reset_action_limiters()
