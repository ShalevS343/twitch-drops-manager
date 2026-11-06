from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    box_art_url: str = ""
    twitch_game_id: str | None = None
    selected: bool = False
    campaign_count: int = 0


class RewardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    benefit_name: str = ""
    required_minutes: int = 0


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    name: str
    status: str
    starts_at: str | None = None
    ends_at: str | None = None
    details_url: str = ""
    owner_name: str = ""
    game: GameOut
    rewards: list[RewardOut] = Field(default_factory=list)


class StreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_login: str
    user_name: str
    title: str
    viewers: int
    language: str
    started_at: str | None = None
    url: str
    live: bool
    game: GameOut
    matching_campaigns: list[str] = Field(default_factory=list)


class ScanRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None = None
    ok: bool
    error: str | None = None
    campaign_count: int = 0
    stream_count: int = 0


class ScanResultOut(BaseModel):
    ok: bool = True
    campaign_count: int
    stream_count: int
    notified_count: int


class StatusOut(BaseModel):
    app: str
    twitch_configured: bool
    telegram_configured: bool
    games_selected: list[str]
    campaign_count: int
    stream_count: int
    last_scan: ScanRunOut | None = None
    last_error: str | None = None


class GamesUpdate(BaseModel):
    games: list[str] = Field(default_factory=list)
