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
    text,
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
        # A chat may be linked to at most one account, but many users have no
        # chat (landing on the same empty string). The link service trims chat
        # ids before saving; this index is a race-safe backstop.
        Index(
            "uq_users_telegram_chat_id",
            "telegram_chat_id",
            unique=True,
            sqlite_where=text("telegram_chat_id <> ''"),
            postgresql_where=text("telegram_chat_id <> ''"),
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
    # Default games are seeded exactly once. A user who deliberately clears all
    # games must not get them back on the next login.
    games_seeded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TelegramLinkCode(Base):
    """One-time, short-lived code that binds a Telegram private chat to a user.

    Only the SHA-256 hash of the code is stored; the plaintext lives in the
    deep link handed to the browser.
    """

    __tablename__ = "telegram_link_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
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
    # Twitch binds an access token to the client that issued it. Legacy rows
    # have an empty value and fall back to the configured Android client.
    client_id: Mapped[str] = mapped_column(
        String(64), default="", server_default="", nullable=False
    )
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


class TwitchDeviceFlow(Base):
    """Short-lived Twitch device authorization started by the login UI.

    ``flow_id`` is the only value handed to the browser. ``device_code`` never
    leaves the server and is never logged.
    """

    __tablename__ = "twitch_device_flows"
    __table_args__ = (Index("ix_twitch_device_flows_expires", "expires_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    flow_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    device_code: Mapped[str] = mapped_column(Text, nullable=False)
    user_code: Mapped[str] = mapped_column(String(32), default="")
    verification_uri: Mapped[str] = mapped_column(String(255), default="")
    client_id: Mapped[str] = mapped_column(String(64), default="")
    invite_code: Mapped[str] = mapped_column(String(255), default="")
    current_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
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
