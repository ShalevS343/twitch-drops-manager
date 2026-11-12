from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    box_art_url: Mapped[str] = mapped_column(String(512), default="")
    twitch_game_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="", index=True)
    starts_at: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ends_at: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details_url: Mapped[str] = mapped_column(String(1024), default="")
    owner_name: Mapped[str] = mapped_column(String(255), default="")
    allow: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Only ever written (see CampaignRepository.upsert_many); deferring avoids
    # loading the large raw payload on every full Campaign query.
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    game: Mapped[Game] = relationship(lazy="selectin")
    rewards: Mapped[list[Reward]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", lazy="selectin"
    )


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    benefit_name: Mapped[str] = mapped_column(String(512), default="")
    required_minutes: Mapped[int] = mapped_column(Integer, default=0)

    campaign: Mapped[Campaign] = relationship(back_populates="rewards")


class Stream(Base):
    __tablename__ = "streams"
    __table_args__ = (UniqueConstraint("user_login", "game_id", name="uq_stream_login_game"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_login: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(255), default="")
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text, default="")
    viewers: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String(16), default="")
    started_at: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str] = mapped_column(String(1024), default="")
    live: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    game: Mapped[Game] = relationship(lazy="selectin")
    matches: Mapped[list[StreamCampaignMatch]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def matching_campaigns(self) -> list[str]:
        return [match.campaign.name for match in self.matches if match.campaign is not None]


class StreamCampaignMatch(Base):
    __tablename__ = "stream_campaign_matches"
    __table_args__ = (
        UniqueConstraint("stream_id", "campaign_id", name="uq_match_stream_campaign"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    eligibility: Mapped[str] = mapped_column(
        String(255), default="Potential campaign match; verify on Twitch"
    )

    stream: Mapped[Stream] = relationship(back_populates="matches")
    campaign: Mapped[Campaign] = relationship(lazy="selectin")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CampaignStart(Base):
    """A campaign start waiting to be delivered to Telegram.

    The row is created when a tracked game's campaign transitions to ACTIVE and
    removed after a successful notification. If Telegram fails, the row stays and
    the next scan retries; the ``notifications`` claim prevents duplicates.
    """

    __tablename__ = "campaign_starts"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )



class CampaignCompletion(Base):
    """A campaign the user has fully claimed.

    Twitch's ``dropCampaignsInProgress`` stops returning a campaign once all
    rewards are claimed, so completion is persisted separately and survives the
    replacement of ``drop_progress``.
    """

    __tablename__ = "campaign_completions"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_gql_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True
    )
    campaign_name: Mapped[str] = mapped_column(String(512), default="")
    game_name: Mapped[str] = mapped_column(String(255), default="")
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TwitchProfile(Base):
    """Persisted Twitch display profile for the connected account.

    Keeping this in its own table (rather than altering ``twitch_auth``) lets
    ``create_all`` add it to an existing database. There is at most one row.
    """

    __tablename__ = "twitch_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=""
    )
    display_name: Mapped[str] = mapped_column(String(255), default="")
    profile_image_url: Mapped[str] = mapped_column(String(1024), default="")
    connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TwitchAuth(Base):
    """User-level Twitch OAuth tokens used to read the drops inventory."""

    __tablename__ = "twitch_auth"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    login: Mapped[str] = mapped_column(String(128), default="")
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DropProgress(Base):
    """Latest known progress for a drop in one of the user's in-progress campaigns."""

    __tablename__ = "drop_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    drop_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    drop_name: Mapped[str] = mapped_column(String(255), default="")
    drop_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    campaign_gql_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    campaign_name: Mapped[str] = mapped_column(String(512), default="")
    campaign_ends_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    game_name: Mapped[str] = mapped_column(String(255), default="")
    game_box_art_url: Mapped[str] = mapped_column(String(1024), default="")

    starts_at: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ends_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    required_minutes: Mapped[int] = mapped_column(Integer, default=0)
    current_minutes: Mapped[int] = mapped_column(Integer, default=0)
    is_claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    benefits: Mapped[list[str]] = mapped_column(JSON, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WatchFocus(Base):
    """Singleton focus pointer for the read-only queue watcher.

    Focused mode allows exactly one watcher (row ``id=1``). The row records which
    live stream/campaign the user should look at next. It is a focus pointer,
    not a playback controller: it never sends watch heartbeats or simulates
    viewing.
    """

    __tablename__ = "watch_focus"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_watch_focus_singleton"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    reason: Mapped[str] = mapped_column(String(64), default="")

    stream_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_login: Mapped[str] = mapped_column(String(128), default="")
    user_name: Mapped[str] = mapped_column(String(255), default="")
    stream_url: Mapped[str] = mapped_column(String(1024), default="")
    stream_title: Mapped[str] = mapped_column(Text, default="")
    game_name: Mapped[str] = mapped_column(String(255), default="")
    game_box_art_url: Mapped[str] = mapped_column(String(1024), default="")

    campaign_id: Mapped[str] = mapped_column(String(128), default="")
    campaign_name: Mapped[str] = mapped_column(String(512), default="")
    target_minutes: Mapped[int] = mapped_column(Integer, default=0)
    ends_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    focused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProgressSnapshot(Base):
    """A point-in-time reading used to estimate the watch rate."""

    __tablename__ = "progress_snapshots"
    __table_args__ = (
        Index(
            "ix_progress_snapshots_drop_recorded",
            "drop_id",
            "recorded_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    drop_id: Mapped[str] = mapped_column(String(128), index=True)
    current_minutes: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign_count: Mapped[int] = mapped_column(Integer, default=0)
    stream_count: Mapped[int] = mapped_column(Integer, default=0)


class User(Base):
    """Local account permanently bound to one Twitch user id.

    Twitch is the only identity provider. The token and sync health live in
    ``twitch_accounts``; this row owns the public profile and account settings.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "length(twitch_user_id) > 0", name="ck_users_twitch_user_id_nonempty"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    twitch_user_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    login: Mapped[str] = mapped_column(String(128), default="")
    display_name: Mapped[str] = mapped_column(String(255), default="")
    profile_image_url: Mapped[str] = mapped_column(String(1024), default="")
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_chat_id: Mapped[str] = mapped_column(String(64), default="")
    telegram_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserSession(Base):
    """Opaque server-side session. Only the SHA-256 hashes are persisted."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    csrf_token_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )


class TwitchAccount(Base):
    """Per-user Twitch OAuth token and sync health."""

    __tablename__ = "twitch_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    access_token: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(Text, default="")
    reconnect_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class UserGame(Base):
    """A game selected for tracking by one user."""

    __tablename__ = "user_games"
    __table_args__ = (
        UniqueConstraint("user_id", "game_id", name="uq_user_games_user_game"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserDropProgress(Base):
    """Latest known progress for a drop, scoped to one user."""

    __tablename__ = "user_drop_progress"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "drop_id", name="uq_user_drop_progress_user_drop"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    drop_id: Mapped[str] = mapped_column(String(128), index=True)
    drop_name: Mapped[str] = mapped_column(String(255), default="")
    drop_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    campaign_gql_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    campaign_name: Mapped[str] = mapped_column(String(512), default="")
    campaign_ends_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    game_name: Mapped[str] = mapped_column(String(255), default="")
    game_box_art_url: Mapped[str] = mapped_column(String(1024), default="")

    starts_at: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ends_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    required_minutes: Mapped[int] = mapped_column(Integer, default=0)
    current_minutes: Mapped[int] = mapped_column(Integer, default=0)
    is_claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    benefits: Mapped[list[str]] = mapped_column(JSON, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UserProgressSnapshot(Base):
    """A point-in-time reading used to estimate one user's watch rate."""

    __tablename__ = "user_progress_snapshots"
    __table_args__ = (
        Index(
            "ix_user_progress_snapshots_user_drop_recorded",
            "user_id",
            "drop_id",
            "recorded_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    drop_id: Mapped[str] = mapped_column(String(128), index=True)
    current_minutes: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserCampaignCompletion(Base):
    """A campaign fully claimed by one user."""

    __tablename__ = "user_campaign_completions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "campaign_gql_id",
            name="uq_user_campaign_completions_user_campaign",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    campaign_gql_id: Mapped[str] = mapped_column(String(128), index=True)
    campaign_name: Mapped[str] = mapped_column(String(512), default="")
    game_name: Mapped[str] = mapped_column(String(255), default="")
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UserWatchFocus(Base):
    """One focus pointer per user (no singleton id check)."""

    __tablename__ = "user_watch_focus"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    reason: Mapped[str] = mapped_column(String(64), default="")

    stream_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_login: Mapped[str] = mapped_column(String(128), default="")
    user_name: Mapped[str] = mapped_column(String(255), default="")
    stream_url: Mapped[str] = mapped_column(String(1024), default="")
    stream_title: Mapped[str] = mapped_column(Text, default="")
    game_name: Mapped[str] = mapped_column(String(255), default="")
    game_box_art_url: Mapped[str] = mapped_column(String(1024), default="")

    campaign_id: Mapped[str] = mapped_column(String(128), default="")
    campaign_name: Mapped[str] = mapped_column(String(512), default="")
    target_minutes: Mapped[int] = mapped_column(Integer, default=0)
    ends_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    focused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UserNotification(Base):
    """Per-user dedupe ledger for Telegram notifications."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "dedupe_key", name="uq_user_notifications_user_dedupe"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(512))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserCampaignStart(Base):
    """A campaign start waiting to be delivered to one user."""

    __tablename__ = "user_campaign_starts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "external_id", name="uq_user_campaign_starts_user_external"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(512))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class AppMeta(Base):
    """Small key/value table for migration and version flags."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
