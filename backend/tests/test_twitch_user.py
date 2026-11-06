from app.providers.twitch_user import TwitchUserProvider


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
