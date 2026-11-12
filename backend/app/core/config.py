from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TWITCH_DEVICE_CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"


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
    # TwitchDropsMiner). Leave the env var blank to use this default.
    twitch_device_client_id: str = ""
    twitch_device_client_secret: str = ""
    twitch_oauth_redirect_uri: str = "https://www.twitch.tv/"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    registration_code: str = ""
    registration_open: bool = False
    owner_twitch_id: str = ""
    session_ttl_days: int = 30
    # "auto" derives Secure from the effective (forwarded) request scheme.
    session_cookie_secure: str = "auto"
    public_origin: str = ""
    allowed_hosts: str = ""
    auth_rate_limit_per_minute: int = 10
    auth_global_rate_limit_per_minute: int = 120

    poll_seconds: int = 900
    min_poll_seconds: int = 300
    progress_poll_seconds: int = 300
    min_progress_poll_seconds: int = 60
    watcher_poll_seconds: int = 60
    min_watcher_poll_seconds: int = 30
    default_games: str = "Rust,Minecraft"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def default_game_list(self) -> list[str]:
        return [name.strip() for name in self.default_games.split(",") if name.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def public_origin_value(self) -> str:
        return self.public_origin.strip().rstrip("/")

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
    def watcher_interval_seconds(self) -> int:
        return max(self.min_watcher_poll_seconds, self.watcher_poll_seconds)

    @property
    def gql_client_id(self) -> str:
        """Client ID used for the internal Twitch GraphQL API.

        The implicit login and the GQL request must use the same client,
        because Twitch binds the access token to the client that issued it.
        """
        return self.twitch_gql_client_id or self.device_client_id

    @property
    def device_client_id(self) -> str:
        """Twitch first-party client used for the progress login (blank = default)."""
        return self.twitch_device_client_id or DEFAULT_TWITCH_DEVICE_CLIENT_ID


@lru_cache
def get_settings() -> Settings:
    return Settings()
