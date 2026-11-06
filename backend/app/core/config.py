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

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    poll_seconds: int = 900
    min_poll_seconds: int = 300
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
