"""Regression tests for Twitch client-secret leaks (H-2)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.api.v1.status import status
from app.core.config import Settings
from app.core.exceptions import (
    SAFE_SCAN_ERROR_PREFIX,
    ProviderError,
)
from app.domain.models import ScanRun
from app.domain.schemas import ScanRunOut
from app.providers.twitch import TOKEN_URL, TwitchProvider
from app.services.scan_service import ScanService
from tests.support import create_user, make_engine

SECRET = "super-secret-client-value"


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self.payload = payload or {"access_token": "token", "expires_in": 3600}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", TOKEN_URL)
            raise httpx.HTTPStatusError(
                "upstream error", request=request, response=self
            )

    def json(self):
        return self.payload


class RecordingClient:
    def __init__(self, *, response=None, error=None) -> None:
        self.requests: list[dict] = []
        self.response = response or FakeResponse()
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, data=None, params=None, json=None):
        self.requests.append(
            {"url": url, "data": data, "params": params, "json": json}
        )
        if self.error is not None:
            raise self.error
        return self.response


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "twitch_client_id": "client-id",
        "twitch_client_secret": SECRET,
        "default_games": "",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_client_credentials_are_sent_in_the_body_not_the_query(monkeypatch):
    from app.providers import twitch as twitch_module

    client = RecordingClient()
    monkeypatch.setattr(
        twitch_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    provider = TwitchProvider(_settings())
    assert await provider._get_token() == "token"

    request = client.requests[0]
    assert request["url"] == TOKEN_URL
    assert request["params"] is None
    assert SECRET not in request["url"]
    assert request["data"] == {
        "client_id": "client-id",
        "client_secret": SECRET,
        "grant_type": "client_credentials",
    }


@pytest.mark.asyncio
async def test_token_transport_errors_never_expose_the_secret(monkeypatch):
    from app.providers import twitch as twitch_module

    class ErrorClient(RecordingClient):
        async def post(self, url, data=None, params=None, json=None):
            self.requests.append({"url": url, "data": data})
            request = httpx.Request(
                "POST", f"{TOKEN_URL}?client_secret={SECRET}"
            )
            raise httpx.ConnectError(
                f"failed POST {request.url}", request=request
            )

    client = ErrorClient()
    monkeypatch.setattr(
        twitch_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    provider = TwitchProvider(_settings())
    with pytest.raises(ProviderError) as excinfo:
        await provider._get_token()

    message = str(excinfo.value)
    assert SECRET not in message
    assert "id.twitch.tv" not in message
    assert "ConnectError" in message


class FailingSunkwi:
    def __init__(self, message: str) -> None:
        self.message = message

    async def fetch_games(self):
        raise RuntimeError(self.message)


class FakeTwitch:
    ready = True

    async def get_streams(self, game_id, max_pages=5):
        return []


class FakeTelegram:
    configured = False


@pytest.mark.asyncio
async def test_scan_error_is_sanitized_and_never_exposes_the_secret(caplog):
    engine, factory = await make_engine()
    leaky_message = f"token request failed: {TOKEN_URL}?client_secret={SECRET}"

    async with factory() as session:
        service = ScanService(
            session=session,
            settings=_settings(twitch_client_id=""),
            sunkwi=FailingSunkwi(leaky_message),
            twitch=FakeTwitch(),
            telegram=FakeTelegram(),
        )
        with (
            caplog.at_level("ERROR", logger="app.services.scan_service"),
            pytest.raises(RuntimeError),
        ):
            await service.run()

        run = (await session.execute(select(ScanRun))).scalar_one()
        assert run.error == "RuntimeError: scan failed"
        assert SECRET not in (run.error or "")
        assert SECRET not in caplog.text
        assert "id.twitch.tv" not in caplog.text

        payload = ScanRunOut.model_validate(run).model_dump_json()
        assert SECRET not in payload

    await engine.dispose()


@pytest.mark.asyncio
async def test_status_and_scan_outputs_redact_legacy_raw_errors(monkeypatch):
    engine, factory = await make_engine()
    legacy_error = f"POST {TOKEN_URL}?client_secret={SECRET} failed"
    settings = _settings()

    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one")
        session.add(
            ScanRun(
                ok=False,
                error=legacy_error,
                campaign_count=0,
                stream_count=0,
            )
        )
        await session.commit()

        run = (await session.execute(select(ScanRun))).scalar_one()
        scans_payload = ScanRunOut.model_validate(run).model_dump_json()
        assert SECRET not in scans_payload
        assert "id.twitch.tv" not in scans_payload
        assert SAFE_SCAN_ERROR_PREFIX in scans_payload

        monkeypatch.setattr("app.api.v1.status.get_settings", lambda: settings)
        result = await status(session, user)
        status_payload = result.model_dump_json()
        assert SECRET not in status_payload
        assert "id.twitch.tv" not in status_payload
        assert result.last_error == SAFE_SCAN_ERROR_PREFIX

    await engine.dispose()
