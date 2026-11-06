from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Twitch Drops Manager"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./data/drops.db"
    cors_origins: str = "http://localhost:5173"
    api_token: str = ""

    sunkwi_url: str = "https://drops.sunkwi.com/api/twitch/drops"
    drops_api_key: str = ""
    drops_cache_seconds_anon: int = 300
    drops_cache_seconds_keyed: int = 60

    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    twitch_gql_url: str = "https://gql.twitch.tv/gql"
    twitch_gql_client_id: str = ""
    # Public first-party Twitch client used only for the read-only drops
    # inventory. Twitch's GQL rejects tokens issued to third-party apps, so the
    # login must use Twitch's own Android client (same approach as
    # TwitchDropsMiner). The user authorizes via Twitch's implicit login and
    # pastes the resulting redirect URL back into the app.
    twitch_device_client_id: str = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"
    twitch_device_client_secret: str = ""
    twitch_oauth_redirect_uri: str = "https://www.twitch.tv/"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    poll_seconds: int = 900
    min_poll_seconds: int = 300
    progress_poll_seconds: int = 300
    min_progress_poll_seconds: int = 60
    default_games: str = "Rust,Minecraft"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def default_game_list(self) -> list[str]:
        return [name.strip() for name in self.default_games.split(",") if name.strip()]

    @property
    def drops_cache_seconds(self) -> int:
        if self.drops_api_key:
            return self.drops_cache_seconds_keyed
        return self.drops_cache_seconds_anon

    @property
    def poll_interval_seconds(self) -> int:
        return max(self.min_poll_seconds, self.poll_seconds)

    @property
    def progress_interval_seconds(self) -> int:
        return max(self.min_progress_poll_seconds, self.progress_poll_seconds)

    @property
    def gql_client_id(self) -> str:
        """Client ID used for the internal Twitch GraphQL API.

        The implicit login and the GQL request must use the same client,
        because Twitch binds the access token to the client that issued it.
        """
        return self.twitch_gql_client_id or self.twitch_device_client_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
