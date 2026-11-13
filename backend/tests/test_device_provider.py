"""Twitch device grant and per-client GraphQL headers."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import (
    DeviceFlowAccessDeniedError,
    DeviceFlowExpiredTokenError,
    DeviceFlowPendingError,
    DeviceFlowSlowDownError,
    DeviceFlowTerminalError,
    ProviderError,
)
from app.providers import twitch_user
from app.providers.twitch_user import TwitchUserProvider

SMART_TV = "ue6666qo983tsx6so1t0vnawi233wa"
ANDROID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None, data=None):
        self.requests.append(
            {"url": url, "headers": headers, "json": json, "data": data}
        )
        return self.responses.pop(0)


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "twitch_gql_client_id": "android-gql",
        "twitch_device_client_id": ANDROID,
        "twitch_gql_url": "https://gql.test/gql",
    }
    values.update(overrides)
    return Settings(**values)


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(twitch_user.httpx, "AsyncClient", lambda **kwargs: client)


@pytest.mark.asyncio
async def test_start_device_flow_uses_smart_tv_client_and_no_scopes(monkeypatch):
    body = {
        "device_code": "device-secret",
        "user_code": "ABCD1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }
    client = FakeClient([FakeResponse(body)])
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings(twitch_device_grant_client_id=""))
    result = await provider.start_device_flow()

    assert result == body
    request = client.requests[0]
    assert request["url"] == "https://id.twitch.tv/oauth2/device"
    assert request["data"] == {"client_id": SMART_TV, "scopes": ""}


@pytest.mark.asyncio
async def test_start_device_flow_failure_does_not_leak_response_body(monkeypatch):
    client = FakeClient(
        [FakeResponse({"message": "invalid client super-secret"}, status_code=400)]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    with pytest.raises(ProviderError) as excinfo:
        await provider.start_device_flow()

    assert "super-secret" not in str(excinfo.value)
    assert "400" in str(excinfo.value)


@pytest.mark.asyncio
async def test_poll_device_token_success_returns_token(monkeypatch):
    client = FakeClient(
        [
            FakeResponse(
                {
                    "access_token": "access-token",
                    "expires_in": 3600,
                    "token_type": "bearer",
                }
            )
        ]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    token = await provider.poll_device_token("device-secret", SMART_TV)

    assert token["access_token"] == "access-token"
    request = client.requests[0]
    assert request["url"] == "https://id.twitch.tv/oauth2/token"
    assert request["data"] == {
        "client_id": SMART_TV,
        "device_code": "device-secret",
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }


@pytest.mark.parametrize(
    ("message", "error"),
    [
        ("authorization_pending", DeviceFlowPendingError),
        ("slow_down", DeviceFlowSlowDownError),
        ("expired_token", DeviceFlowExpiredTokenError),
        ("access_denied", DeviceFlowAccessDeniedError),
    ],
)
@pytest.mark.asyncio
async def test_poll_device_token_maps_oauth_errors(monkeypatch, message, error):
    client = FakeClient(
        [FakeResponse({"status": 400, "message": message}, status_code=400)]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    with pytest.raises(error) as excinfo:
        await provider.poll_device_token("device-secret", SMART_TV)

    assert "device-secret" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_poll_device_token_terminal_error_is_sanitized(monkeypatch):
    client = FakeClient(
        [FakeResponse({"message": "invalid device-code"}, status_code=400)]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    with pytest.raises(DeviceFlowTerminalError) as excinfo:
        await provider.poll_device_token("device-code-value", SMART_TV)

    assert "invalid device-code" not in str(excinfo.value)
    assert "device-code-value" not in str(excinfo.value)
    assert "400" in str(excinfo.value)


@pytest.mark.asyncio
async def test_poll_device_token_5xx_is_a_transient_provider_error(monkeypatch):
    client = FakeClient(
        [FakeResponse({"message": "upstream unavailable"}, status_code=503)]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    with pytest.raises(ProviderError) as excinfo:
        await provider.poll_device_token("device-secret", SMART_TV)

    assert not isinstance(excinfo.value, DeviceFlowTerminalError)
    assert "upstream unavailable" not in str(excinfo.value)
    assert "503" in str(excinfo.value)


@pytest.mark.asyncio
async def test_fetch_inventory_uses_the_supplied_client_id(monkeypatch):
    client = FakeClient(
        [FakeResponse({"data": {"currentUser": {"inventory": {}}}})]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    await provider.fetch_inventory("token", SMART_TV)

    assert client.requests[0]["headers"]["Client-Id"] == SMART_TV


@pytest.mark.asyncio
async def test_fetch_inventory_falls_back_to_the_configured_client(monkeypatch):
    client = FakeClient(
        [FakeResponse({"data": {"currentUser": {"inventory": {}}}})]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    await provider.fetch_inventory("token")

    assert client.requests[0]["headers"]["Client-Id"] == "android-gql"


@pytest.mark.asyncio
async def test_fetch_profile_uses_the_supplied_client_id(monkeypatch):
    client = FakeClient(
        [FakeResponse({"data": {"currentUser": {"id": "123", "login": "viewer"}}})]
    )
    _patch_client(monkeypatch, client)

    provider = TwitchUserProvider(_settings())
    await provider.fetch_profile("token", "123", client_id=SMART_TV)

    assert client.requests[0]["headers"]["Client-Id"] == SMART_TV
