from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    completed: bool = False
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
    user: AuthUserOut | None = None
    twitch_configured: bool
    telegram_configured: bool
    telegram_ready: bool = False
    games_selected: list[str]
    campaign_count: int
    stream_count: int
    last_scan: ScanRunOut | None = None
    last_error: str | None = None
    twitch_user_connected: bool = False
    twitch_login: str | None = None
    poll_seconds: int = 900
    min_poll_seconds: int = 300
    progress_poll_seconds: int = 300
    min_progress_poll_seconds: int = 60
    watcher_poll_seconds: int = 60
    min_watcher_poll_seconds: int = 30
    drops_api_keyed: bool = False


class GamesUpdate(BaseModel):
    games: list[str] = Field(default_factory=list)


class ProgressDropOut(BaseModel):
    drop_id: str
    drop_name: str
    required_minutes: int = 0
    current_minutes: int = 0
    percent: int = 0
    is_claimed: bool = False
    is_ready: bool = False
    starts_at: str | None = None
    ends_at: str | None = None
    benefits: list[str] = Field(default_factory=list)
    remaining_minutes: int = 0
    rate_minutes_per_hour: float | None = None


class ProgressCampaignOut(BaseModel):
    campaign_id: str
    campaign_name: str
    game_name: str = ""
    game_box_art_url: str = ""
    campaign_ends_at: str | None = None
    claimed_count: int = 0
    total_count: int = 0
    drops: list[ProgressDropOut] = Field(default_factory=list)
    remaining_minutes: int = 0


class WatchQueueCampaignOut(BaseModel):
    campaign_id: str
    campaign_name: str
    ends_at: str | None = None
    remaining_minutes: int = 0
    next_drop_name: str | None = None
    next_drop_remaining_minutes: int | None = None


class WatchQueueItemOut(BaseModel):
    stream_id: int
    user_login: str
    user_name: str
    title: str
    viewers: int
    language: str
    url: str
    game_name: str
    game_box_art_url: str
    campaigns: list[WatchQueueCampaignOut] = Field(default_factory=list)


class WatchCandidateOut(BaseModel):
    """One dispatchable live stream/campaign pair for focused mode."""

    stream_id: int
    user_login: str
    user_name: str
    stream_url: str
    stream_title: str
    game_name: str = ""
    game_box_art_url: str = ""
    viewers: int = 0
    campaign_id: str
    campaign_name: str
    target_minutes: int = 0
    ends_at: str | None = None


class WatchFocusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stream_id: int | None = None
    user_login: str = ""
    user_name: str = ""
    stream_url: str = ""
    stream_title: str = ""
    game_name: str = ""
    game_box_art_url: str = ""
    campaign_id: str = ""
    campaign_name: str = ""
    target_minutes: int = 0
    ends_at: str | None = None
    reason: str = ""
    focused_at: datetime | None = None
    updated_at: datetime | None = None


class WatchStateOut(BaseModel):
    enabled: bool = False
    status: Literal["idle", "focused", "offline", "waiting"] = "idle"
    reason: str = ""
    max_watchers: int = 1
    auto_move: bool = False
    focus: WatchFocusOut | None = None
    candidates: list[WatchCandidateOut] = Field(default_factory=list)
    updated_at: datetime | None = None


class WatchFocusIn(BaseModel):
    """Dispatch the single watcher.

    ``manual`` requires ``stream_id`` + ``campaign_id``; ``auto`` picks the most
    urgent live candidate; ``next`` picks another live stream than the current
    focus.
    """

    stream_id: int | None = None
    campaign_id: str | None = None
    strategy: Literal["manual", "auto", "next"] = "manual"


class WatchToggleIn(BaseModel):
    enabled: bool


class ProgressRefreshOut(BaseModel):
    connected: bool
    campaign_count: int = 0
    drop_count: int = 0
    notified_count: int = 0


class TwitchUserStatusOut(BaseModel):
    connected: bool = False
    login: str | None = None
    user_id: str | None = None
    expires_at: datetime | None = None
    display_name: str | None = None
    profile_image_url: str | None = None
    connected_at: datetime | None = None
    reconnect_required: bool = False
    last_error: str | None = None
    last_synced_at: datetime | None = None


class TwitchConnectOut(BaseModel):
    authorize_url: str
    redirect_uri: str


class AuthUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    display_name: str
    profile_image_url: str
    role: str
    telegram_enabled: bool
    telegram_chat_id: str


class RegistrationStateOut(BaseModel):
    open: bool
    invite_required: bool


class AuthMeOut(BaseModel):
    authenticated: bool
    user: AuthUserOut | None = None
    registration: RegistrationStateOut
    telegram_bot_configured: bool = False


class AuthConnectIn(BaseModel):
    redirect_url: str
    invite_code: str = ""


class AuthConnectOut(BaseModel):
    connected: bool = True
    user: AuthUserOut
    created: bool = False


class TelegramSettingsIn(BaseModel):
    telegram_chat_id: str = ""
    telegram_enabled: bool = False


class TelegramLinkOut(BaseModel):
    deep_link: str
    expires_at: datetime


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    telegram_enabled: bool


class AdminUserUpdate(BaseModel):
    is_active: bool
