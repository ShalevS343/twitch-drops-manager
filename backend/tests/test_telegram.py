import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import NotConfiguredError, ProviderError
from app.providers.telegram import TelegramConflictError, TelegramProvider

BOT_TOKEN = "123456:super-secret-bot-token"


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class RecordingClient:
    def __init__(self, *, response=None, error=None) -> None:
        self.requests = []
        self.response = response or FakeResponse()
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, json=None):
        self.requests.append((url, json))
        if self.error is not None:
            raise self.error
        return self.response


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "telegram_bot_token": BOT_TOKEN,
        "telegram_chat_id": "",
    }
    values.update(overrides)
    return Settings(**values)


def test_configured_means_only_the_bot_token_is_present():
    assert TelegramProvider(_settings()).configured is True
    assert TelegramProvider(_settings(telegram_bot_token="")).configured is False


@pytest.mark.asyncio
async def test_send_targets_the_requested_chat(monkeypatch):
    from app.providers import telegram as telegram_module

    client = RecordingClient()
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    await TelegramProvider(_settings()).send("hello", "987654")

    _url, payload = client.requests[0]
    assert payload["chat_id"] == "987654"
    assert payload["text"] == "hello"


@pytest.mark.asyncio
async def test_send_requires_a_chat_id():
    with pytest.raises(ProviderError):
        await TelegramProvider(_settings()).send("hello", "")


@pytest.mark.asyncio
async def test_send_requires_a_bot_token():
    with pytest.raises(NotConfiguredError):
        await TelegramProvider(_settings(telegram_bot_token="")).send(
            "hello", "123"
        )


@pytest.mark.asyncio
async def test_transport_error_redacts_the_bot_token_and_url(monkeypatch):
    from app.providers import telegram as telegram_module

    request = httpx.Request(
        "POST", f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    )
    client = RecordingClient(error=httpx.ConnectError("boom", request=request))
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(ProviderError) as excinfo:
        await TelegramProvider(_settings()).send("hello", "123")

    message = str(excinfo.value)
    assert BOT_TOKEN not in message
    assert "api.telegram.org" not in message
    assert "ConnectError" in message


@pytest.mark.asyncio
async def test_http_error_redacts_the_bot_token_and_url(monkeypatch):
    from app.providers import telegram as telegram_module

    client = RecordingClient(response=FakeResponse(status_code=400))
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(ProviderError) as excinfo:
        await TelegramProvider(_settings()).send("hello", "123")

    message = str(excinfo.value)
    assert BOT_TOKEN not in message
    assert "api.telegram.org" not in message
    assert "400" in message


@pytest.mark.asyncio
async def test_get_me_returns_and_caches_the_bot_username(monkeypatch):
    from app.providers import telegram as telegram_module

    client = RecordingClient(
        response=FakeResponse(
            payload={
                "ok": True,
                "result": {"id": 1, "username": "raspberrypitwitchbot"},
            }
        )
    )
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )
    provider = TelegramProvider(_settings())

    first = await provider.get_me()
    second = await provider.get_me()

    assert first["username"] == "raspberrypitwitchbot"
    assert second is first
    assert len(client.requests) == 1
    assert client.requests[0][0].endswith("/getMe")
    assert BOT_TOKEN in client.requests[0][0]


@pytest.mark.asyncio
async def test_get_updates_sends_offset_timeout_and_allowed_updates(monkeypatch):
    from app.providers import telegram as telegram_module

    client = RecordingClient(
        response=FakeResponse(
            payload={"ok": True, "result": [{"update_id": 12}]}
        )
    )
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    updates = await TelegramProvider(_settings()).get_updates(11)

    assert updates == [{"update_id": 12}]
    url, payload = client.requests[0]
    assert url.endswith("/getUpdates")
    assert payload["offset"] == 11
    assert payload["timeout"] == 25
    assert payload["allowed_updates"] == ["message"]


@pytest.mark.asyncio
async def test_get_updates_omits_a_missing_offset(monkeypatch):
    from app.providers import telegram as telegram_module

    client = RecordingClient(
        response=FakeResponse(payload={"ok": True, "result": []})
    )
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    assert await TelegramProvider(_settings()).get_updates(None) == []
    _url, payload = client.requests[0]
    assert "offset" not in payload


@pytest.mark.asyncio
async def test_get_updates_409_raises_a_conflict_without_the_token(monkeypatch):
    from app.providers import telegram as telegram_module

    client = RecordingClient(response=FakeResponse(status_code=409))
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(TelegramConflictError) as excinfo:
        await TelegramProvider(_settings()).get_updates(1)

    message = str(excinfo.value)
    assert BOT_TOKEN not in message
    assert "api.telegram.org" not in message
    assert "webhook" in message.lower()


@pytest.mark.asyncio
async def test_get_updates_transport_error_redacts_the_token(monkeypatch):
    from app.providers import telegram as telegram_module

    request = httpx.Request(
        "POST", f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    )
    client = RecordingClient(error=httpx.ConnectError("boom", request=request))
    monkeypatch.setattr(
        telegram_module.httpx, "AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(ProviderError) as excinfo:
        await TelegramProvider(_settings()).get_updates(1)

    message = str(excinfo.value)
    assert BOT_TOKEN not in message
    assert "api.telegram.org" not in message
    assert "ConnectError" in message
