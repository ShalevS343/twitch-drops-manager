"""One-transaction, idempotent migration from the single-user schema.

The legacy tables are frozen after migration. New personal data lives in the
``user_*`` tables; the old tables are only read here so the existing owner keeps
their progress after the first Twitch login.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings

MIGRATION_KEY = "multi_user_v1"
MIGRATION_DONE = "done"


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def _has_table(connection: AsyncConnection, name: str) -> bool:
    return bool(
        await connection.run_sync(lambda sync: inspect(sync).has_table(name))
    )


async def _table_row(
    connection: AsyncConnection,
    name: str,
    *,
    where: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    clause = f" WHERE {where}" if where else ""
    result = await connection.execute(
        text(f"SELECT * FROM {name}{clause} ORDER BY id LIMIT 1"), params or {}
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _copy_rows(
    connection: AsyncConnection,
    *,
    legacy_table: str,
    target_table: str,
    owner_id: int,
    columns: list[str],
    where: str = "",
) -> None:
    if not await _has_table(connection, legacy_table):
        return

    target_columns = ["user_id", *columns]
    selects = [":owner_id", *columns]
    clause = f" WHERE {where}" if where else ""
    sql = (
        f"INSERT OR IGNORE INTO {target_table} "
        f"({', '.join(target_columns)}) "
        f"SELECT {', '.join(selects)} FROM {legacy_table}{clause}"
    )
    await connection.execute(text(sql), {"owner_id": owner_id})


async def run_multi_user_migration(connection: AsyncConnection) -> None:
    """Copy legacy single-user data into the user-scoped tables exactly once.

    Must run inside the same transaction that created the new tables. On any
    abort the caller's transaction rolls back, including the migration flag, so
    the next startup retries from a clean slate.
    """
    settings = get_settings()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    claim = await connection.execute(
        text(
            "INSERT OR IGNORE INTO app_meta (key, value, updated_at) "
            "VALUES (:key, 'pending', :now)"
        ),
        {"key": MIGRATION_KEY, "now": now},
    )
    if claim.rowcount == 0:
        current = (
            await connection.execute(
                text("SELECT value FROM app_meta WHERE key = :key"),
                {"key": MIGRATION_KEY},
            )
        ).scalar_one_or_none()
        if current == MIGRATION_DONE:
            return

    users_count = int(
        (await connection.execute(text("SELECT COUNT(*) FROM users"))).scalar_one()
    )
    legacy_auth = (
        await _table_row(connection, "twitch_auth")
        if await _has_table(connection, "twitch_auth")
        else None
    )

    owner_id: int | None = None
    if legacy_auth is not None:
        twitch_user_id = str(legacy_auth.get("user_id") or "").strip()
        if not twitch_user_id:
            raise RuntimeError(
                "Legacy twitch_auth row has an empty user_id. Fix or clear the "
                "legacy twitch_auth.user_id/login, or restore the pre-upgrade "
                "backup, then restart. OWNER_TWITCH_ID only bootstraps an "
                "install with no legacy token; it cannot repair this row."
            )

        owner_id = await _find_user_id(connection, twitch_user_id)
        if owner_id is None:
            if users_count > 0:
                raise RuntimeError(
                    "Legacy Twitch account does not match any users row. "
                    "Refusing to attach legacy data to the wrong "
                    "twitch_user_id; fix the users table and restart."
                )
            profile = None
            if await _has_table(connection, "twitch_profile"):
                profile = await _table_row(
                    connection,
                    "twitch_profile",
                    where="user_id = :twitch_user_id",
                    params={"twitch_user_id": twitch_user_id},
                )
            owner_id = await _create_user(
                connection,
                twitch_user_id=twitch_user_id,
                login=str(legacy_auth.get("login") or ""),
                role="admin",
                now=now,
                profile=profile,
                games_seeded=True,
            )
        else:
            # The migrated owner's copied selection (including an intentionally
            # empty one) is authoritative; never reseed defaults on login.
            await connection.execute(
                text("UPDATE users SET games_seeded = 1 WHERE id = :owner_id"),
                {"owner_id": owner_id},
            )

        await _seed_telegram(
            connection, owner_id=owner_id, settings_chat_id=settings.telegram_chat_id
        )
        await _copy_twitch_account(
            connection,
            owner_id=owner_id,
            legacy_auth=legacy_auth,
            now=now,
        )
    elif users_count == 0 and settings.owner_twitch_id.strip():
        owner_id = await _create_user(
            connection,
            twitch_user_id=settings.owner_twitch_id.strip(),
            login="",
            role="admin",
            now=now,
            profile=None,
            games_seeded=False,
        )
        await _seed_telegram(
            connection, owner_id=owner_id, settings_chat_id=settings.telegram_chat_id
        )

    if owner_id is not None:
        await _copy_personal_rows(connection, owner_id=owner_id, now=now)
        await connection.execute(
            text(
                "INSERT OR IGNORE INTO app_meta (key, value, updated_at) "
                "VALUES ('first_admin_claimed', '1', :now)"
            ),
            {"now": now},
        )

    await connection.execute(
        text("UPDATE app_meta SET value = :value, updated_at = :now WHERE key = :key"),
        {"key": MIGRATION_KEY, "value": MIGRATION_DONE, "now": now},
    )


async def _find_user_id(connection: AsyncConnection, twitch_user_id: str) -> int | None:
    result = await connection.execute(
        text("SELECT id FROM users WHERE twitch_user_id = :twitch_user_id"),
        {"twitch_user_id": twitch_user_id},
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else None


async def _create_user(
    connection: AsyncConnection,
    *,
    twitch_user_id: str,
    login: str,
    role: str,
    now: str,
    profile: dict[str, Any] | None,
    games_seeded: bool,
) -> int:
    display_name = str((profile or {}).get("display_name") or "") or login
    profile_image_url = str((profile or {}).get("profile_image_url") or "")
    result = await connection.execute(
        text(
            "INSERT INTO users (twitch_user_id, login, display_name, "
            "profile_image_url, role, is_active, telegram_chat_id, "
            "telegram_enabled, games_seeded, created_at, updated_at) "
            "VALUES (:twitch_user_id, :login, :display_name, "
            ":profile_image_url, :role, 1, '', 0, :games_seeded, :now, :now)"
        ),
        {
            "twitch_user_id": twitch_user_id,
            "login": login,
            "display_name": display_name,
            "profile_image_url": profile_image_url,
            "role": role,
            "games_seeded": 1 if games_seeded else 0,
            "now": now,
        },
    )
    if result.lastrowid is None:
        owner_id = await _find_user_id(connection, twitch_user_id)
        if owner_id is None:
            raise RuntimeError("Could not create the migrated owner user")
        return owner_id
    return int(result.lastrowid)


async def _seed_telegram(
    connection: AsyncConnection, *, owner_id: int, settings_chat_id: str
) -> None:
    chat_id = settings_chat_id.strip()
    if not chat_id:
        return
    await connection.execute(
        text(
            "UPDATE users SET telegram_chat_id = :chat_id, telegram_enabled = 1, "
            "updated_at = :now "
            "WHERE id = :owner_id "
            "AND (telegram_chat_id IS NULL OR telegram_chat_id = '')"
        ),
        {
            "chat_id": chat_id,
            "owner_id": owner_id,
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )


async def _copy_twitch_account(
    connection: AsyncConnection,
    *,
    owner_id: int,
    legacy_auth: dict[str, Any],
    now: str,
) -> None:
    expires_at = _as_datetime(legacy_auth.get("expires_at"))
    reconnect_required = (
        expires_at is not None and expires_at <= datetime.now(timezone.utc)
    )
    await connection.execute(
        text(
            "INSERT OR IGNORE INTO twitch_accounts "
            "(user_id, access_token, expires_at, connected_at, last_synced_at, "
            "last_error, reconnect_required) "
            "VALUES (:owner_id, :access_token, :expires_at, :connected_at, "
            "NULL, '', :reconnect_required)"
        ),
        {
            "owner_id": owner_id,
            "access_token": str(legacy_auth.get("access_token") or ""),
            "expires_at": legacy_auth.get("expires_at"),
            "connected_at": legacy_auth.get("updated_at") or now,
            "reconnect_required": 1 if reconnect_required else 0,
        },
    )


async def _copy_personal_rows(
    connection: AsyncConnection, *, owner_id: int, now: str
) -> None:
    await _copy_rows(
        connection,
        legacy_table="drop_progress",
        target_table="user_drop_progress",
        owner_id=owner_id,
        columns=[
            "drop_id",
            "drop_name",
            "drop_instance_id",
            "campaign_gql_id",
            "campaign_name",
            "campaign_ends_at",
            "game_name",
            "game_box_art_url",
            "starts_at",
            "ends_at",
            "required_minutes",
            "current_minutes",
            "is_claimed",
            "is_ready",
            "benefits",
            "updated_at",
        ],
    )
    await _copy_rows(
        connection,
        legacy_table="progress_snapshots",
        target_table="user_progress_snapshots",
        owner_id=owner_id,
        columns=["drop_id", "current_minutes", "recorded_at"],
    )
    await _copy_rows(
        connection,
        legacy_table="campaign_completions",
        target_table="user_campaign_completions",
        owner_id=owner_id,
        columns=[
            "campaign_gql_id",
            "campaign_name",
            "game_name",
            "completed_at",
            "updated_at",
        ],
    )
    await _copy_rows(
        connection,
        legacy_table="watch_focus",
        target_table="user_watch_focus",
        owner_id=owner_id,
        columns=[
            "enabled",
            "status",
            "reason",
            "stream_id",
            "user_login",
            "user_name",
            "stream_url",
            "stream_title",
            "game_name",
            "game_box_art_url",
            "campaign_id",
            "campaign_name",
            "target_minutes",
            "ends_at",
            "focused_at",
            "updated_at",
        ],
        where="id = 1",
    )
    await _copy_rows(
        connection,
        legacy_table="notifications",
        target_table="user_notifications",
        owner_id=owner_id,
        columns=["dedupe_key", "sent_at"],
    )
    await _copy_rows(
        connection,
        legacy_table="campaign_starts",
        target_table="user_campaign_starts",
        owner_id=owner_id,
        columns=["external_id", "detected_at"],
    )
    if await _has_table(connection, "games"):
        await connection.execute(
            text(
                "INSERT OR IGNORE INTO user_games (user_id, game_id, created_at) "
                "SELECT :owner_id, id, :now FROM games WHERE selected = 1"
            ),
            {"owner_id": owner_id, "now": now},
        )
