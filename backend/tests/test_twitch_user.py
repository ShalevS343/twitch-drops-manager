import pytest

from app.core.config import Settings
from app.core.exceptions import ProviderError, ReconnectRequiredError
from app.providers import twitch_user
from app.providers.twitch_user import TwitchUserProvider


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

    async def post(self, url, headers=None, json=None):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        twitch_gql_client_id="test-client",
        twitch_gql_url="https://gql.test/gql",
    )


def test_parse_oauth_token_from_fragment_url():
    url = "https://www.twitch.tv/#access_token=abc123def456&scope=&state=xyz"
    assert TwitchUserProvider.parse_oauth_token(url) == "abc123def456"


def test_parse_oauth_token_from_query_url():
    url = "https://example.test/callback?access_token=abc123def456&scope="
    assert TwitchUserProvider.parse_oauth_token(url) == "abc123def456"


def test_parse_oauth_token_accepts_raw_token():
    assert TwitchUserProvider.parse_oauth_token("abcdefghijklmnopqrstuvwx") == (
        "abcdefghijklmnopqrstuvwx"
    )


def test_parse_oauth_token_rejects_garbage():
    assert TwitchUserProvider.parse_oauth_token("") is None
    assert TwitchUserProvider.parse_oauth_token("not a token") is None
    assert TwitchUserProvider.parse_oauth_token("https://www.twitch.tv/") is None


@pytest.mark.asyncio
async def test_fetch_profile_parses_response_and_uses_cache(monkeypatch):
    response = FakeResponse(
        {
            "data": {
                "currentUser": {
                    "id": "123",
                    "login": "viewer",
                    "displayName": "Viewer Name",
                    "profileImageURL": "https://example.test/avatar.png",
                }
            }
        }
    )
    client = FakeClient([response])
    monkeypatch.setattr(
        twitch_user.httpx, "AsyncClient", lambda **kwargs: client
    )

    provider = TwitchUserProvider(_settings())
    profile = await provider.fetch_profile("token", "123")

    assert profile["displayName"] == "Viewer Name"
    assert profile["profileImageURL"] == "https://example.test/avatar.png"

    request = client.requests[0]
    assert request["url"] == "https://gql.test/gql"
    assert request["headers"]["Client-Id"] == "test-client"
    assert request["headers"]["Authorization"] == "OAuth token"
    assert "ViewerCard" in request["json"]["query"]
    assert "profileImageURL(width: 300)" in request["json"]["query"]

    again = await provider.fetch_profile("token", "123")
    assert again == profile
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_fetch_profile_caches_by_token_when_user_id_missing(monkeypatch):
    client = FakeClient(
        [FakeResponse({"data": {"currentUser": {"id": "1", "login": "viewer"}}})]
    )
    monkeypatch.setattr(
        twitch_user.httpx, "AsyncClient", lambda **kwargs: client
    )

    provider = TwitchUserProvider(_settings())
    await provider.fetch_profile("abcdefgh12345678")
    await provider.fetch_profile("abcdefgh12345678")

    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_fetch_profile_returns_empty_dict_for_missing_user(monkeypatch):
    client = FakeClient([FakeResponse({"data": {"currentUser": None}})])
    monkeypatch.setattr(
        twitch_user.httpx, "AsyncClient", lambda **kwargs: client
    )

    provider = TwitchUserProvider(_settings())
    assert await provider.fetch_profile("token", "123") == {}


@pytest.mark.asyncio
async def test_fetch_profile_raises_reconnect_required_on_401(monkeypatch):
    client = FakeClient([FakeResponse({}, status_code=401)])
    monkeypatch.setattr(
        twitch_user.httpx, "AsyncClient", lambda **kwargs: client
    )

    provider = TwitchUserProvider(_settings())
    with pytest.raises(ReconnectRequiredError):
        await provider.fetch_profile("token", "123")


@pytest.mark.asyncio
async def test_fetch_profile_raises_provider_error_on_rate_limit(monkeypatch):
    client = FakeClient([FakeResponse({}, status_code=429)])
    monkeypatch.setattr(
        twitch_user.httpx, "AsyncClient", lambda **kwargs: client
    )

    provider = TwitchUserProvider(_settings())
    with pytest.raises(ProviderError):
        await provider.fetch_profile("token", "123")


@pytest.mark.asyncio
async def test_fetch_profile_raises_provider_error_on_graphql_errors(monkeypatch):
    client = FakeClient(
        [FakeResponse({"errors": [{"message": "boom"}], "data": None})]
    )
    monkeypatch.setattr(
        twitch_user.httpx, "AsyncClient", lambda **kwargs: client
    )

    provider = TwitchUserProvider(_settings())
    with pytest.raises(ProviderError, match="boom"):
        await provider.fetch_profile("token", "123")
