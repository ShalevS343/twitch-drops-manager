# Data model

SQLite database at `/data/drops.db` inside the `drops_data` Docker volume
(local dev default: `./data/drops.db`). SQLAlchemy async + `aiosqlite`, WAL mode,
`foreign_keys=ON`, `synchronous=NORMAL`, 5s busy timeout.

Multi-user schema: `users` owns identity and profile; each personal table carries
`user_id`; the catalog and live streams stay shared. The former single-user
tables are frozen after migration and are not read by current code (see
[Legacy tables](#legacy-tables-frozen)).

## Ownership rules

- `users.twitch_user_id` is the single authoritative Twitch identity. It is
  required (non-empty) and unique. `twitch_accounts` does not duplicate it.
- `users` owns `login`, `display_name`, `profile_image_url`, `role`,
  `is_active`, `telegram_chat_id` (empty = not set), `telegram_enabled`
  (opt-in), and `games_seeded` (one-time default-game bootstrap).
- `twitch_accounts` owns only the token, expiry, connected timestamp, and sync
  health. Reconnect updates the token row and user profile in one transaction.
- A local user is permanently bound to one Twitch id. Signing in with another
  Twitch account creates/loads a separate user; it never relinks the old one.
- Completion, progress, notification, and start rows cascade on user deletion,
  but the API only disables users rather than deleting them.

## New tables

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `twitch_user_id` | string, **non-empty unique**, indexed | authoritative Twitch id |
| `login` | string | Twitch login |
| `display_name` | string | falls back to login |
| `profile_image_url` | string | |
| `role` | string | `admin` or `user`; first user is `admin` |
| `is_active` | bool | disabled users get no session and are skipped by workers |
| `telegram_chat_id` | string | empty = not set; per-user destination |
| `telegram_enabled` | bool | opt-in |
| `games_seeded` | bool | default `false`; set on first connect or `PUT /games`, so cleared games stay cleared |
| `created_at`, `updated_at` | datetime | |
| `last_login_at` | datetime, nullable | admin list uses created/last login |

### `user_sessions`

Server-side sessions. The raw token exists only in the browser cookie.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → users, indexed, cascade | |
| `token_hash` | string, unique, indexed | SHA-256 of the session token |
| `csrf_token_hash` | string | SHA-256 of the CSRF token; unused by the current double-submit check |
| `created_at` | datetime | |
| `expires_at` | datetime, indexed | absolute expiry, `SESSION_TTL_DAYS` |
| `last_used_at` | datetime | updated at most once per hour |

Expired sessions are pruned at startup and during the worker scan.

### `twitch_accounts`

Per-user OAuth token and sync health.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → users, **unique**, indexed, cascade | one Twitch account per user |
| `access_token` | text | **secret**, plaintext in SQLite |
| `expires_at` | datetime, nullable | null = no known expiry (legacy implicit token) |
| `connected_at` | datetime | set on connect/reconnect |
| `last_synced_at` | datetime, nullable | last successful progress sync |
| `last_error` | text | redacted, user-facing |
| `reconnect_required` | bool | set on user-token 401/expiry; cleared on success |

### `user_games`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → users, indexed, cascade | |
| `game_id` | FK → games, indexed, cascade | |
| `created_at` | datetime | |

Unique `(user_id, game_id)`. Replaces `games.selected` for personal selection.

### `user_drop_progress`

Latest inventory snapshot per user (replaced each sync). Columns mirror the old
`drop_progress` table plus `user_id`; unique `(user_id, drop_id)`. Twitch drop ids
are unique per account, so the pair is the key.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → users, indexed, cascade | |
| `drop_id` | string, indexed | Twitch drop id |
| `drop_name`, `drop_instance_id` | string | |
| `campaign_gql_id`, `campaign_name` | string | |
| `campaign_ends_at` | string, nullable | |
| `game_name`, `game_box_art_url` | string | |
| `starts_at`, `ends_at` | string, nullable | drop window |
| `required_minutes`, `current_minutes` | int | |
| `is_claimed`, `is_ready` | bool | |
| `benefits` | JSON list | |
| `updated_at` | datetime | |

### `user_progress_snapshots`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → users, indexed, cascade | |
| `drop_id` | string | |
| `current_minutes` | int | |
| `recorded_at` | datetime | |

Index `(user_id, drop_id, recorded_at)`. Pruned to the last 24h per user on each
sync. Used for the per-user watch rate.

### `user_campaign_completions`

Per-user completion ledger, derived from `earnedDropRewards`.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → users, indexed, cascade | |
| `campaign_gql_id` | string, indexed | Twitch campaign id |
| `campaign_name`, `game_name` | string | display copy |
| `completed_at`, `updated_at` | datetime | |

Unique `(user_id, campaign_gql_id)`. Completion is permanent for that account.

### `user_watch_focus`

One focus pointer per user (not a singleton). No `id=1` check; `user_id` is
unique. Stores a copy of the focused stream/campaign for rendering without a
join. It is not a playback controller and contains no watch heartbeats.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → users, **unique**, indexed, cascade | |
| `enabled` | bool | focused mode on/off |
| `status` | string | `idle`, `focused`, `offline`, `waiting` |
| `reason` | string | `manual`, `auto`, `live`, `offline`, `completed`, … |
| `stream_id` | int, nullable | current stream row (recreated each scan) |
| `user_login`, `user_name`, `stream_url`, `stream_title` | string | channel snapshot |
| `game_name`, `game_box_art_url` | string | |
| `campaign_id` | string | Twitch GQL campaign id |
| `campaign_name` | string | |
| `target_minutes` | int | remaining watch minutes at focus time |
| `ends_at` | string, nullable | |
| `focused_at`, `updated_at` | datetime | |

The worker matches by `user_login` + `campaign_id` first, then `stream_id`.

### `user_notifications`

Per-user dedupe ledger. Unique `(user_id, dedupe_key)`; `sent_at` datetime. Keys
are the same event names as before, scoped by the user row. Claims are inserted
inside a SAVEPOINT and released after a failed send.

### `user_campaign_starts`

Per-user pending campaign-start events. Unique `(user_id, external_id)` plus
`detected_at`. Created only for users tracking the game **and** Telegram-enabled
with a chat id; deleted after a successful digest, kept for retry on failure,
and pruned when the campaign leaves the catalog.

### `app_meta`

| Column | Type | Notes |
|---|---|---|
| `key` | string PK | |
| `value` | string | |

Holds migration/version flags such as `multi_user_v1`.

## Shared tables

These keep their existing schema and are written once per scan/sync:

- `games` — catalog. `selected` is **legacy** and ignored by the API; per-user
  selection lives in `user_games`. A game tracked by name before it exists in
  the catalog still gets a `Game` row and is linked through `user_games`.
- `campaigns` — shared catalog; `raw` stays deferred.
- `rewards` — shared catalog rewards.
- `streams`, `stream_campaign_matches` — shared live data, replaced each scan.
- `scan_runs` — shared scan audit.

## Legacy tables (frozen)

Created by the single-user release and left in place for rollback. Current code
does not read or write them after migration:

`twitch_auth`, `twitch_profile`, `drop_progress`, `progress_snapshots`,
`campaign_completions`, `notifications`, `campaign_starts`, `watch_focus`
(singleton), and the `games.selected` flag.

Do not drop or edit them during the soak period. A later cleanup release can
remove them once the rollback window has passed.

## Relationships at a glance

```
users 1─1 twitch_accounts
users 1─* user_sessions
users 1─* user_games *─1 games
users 1─* user_drop_progress 1─* user_progress_snapshots
users 1─* user_campaign_completions
users 1─1 user_watch_focus
users 1─* user_notifications
users 1─* user_campaign_starts

games 1─* campaigns 1─* rewards
games 1─* streams 1─* stream_campaign_matches *─1 campaigns
scan_runs (shared audit)        app_meta (migration flags)
```

`user_drop_progress` is deliberately not FK-linked to `campaigns`: inventory
campaign ids come from Twitch GQL and may not exist in the public catalog.
Matching uses the `external_id` suffix (`"{game}:{gql_id}"`).

## Retention / replacement

- `streams`/`stream_campaign_matches`: replaced on every scan.
- `campaigns`/`rewards`: upserted; stale campaigns deleted when absent from the
  catalog.
- `user_drop_progress`: replaced per user on every progress sync.
- `user_progress_snapshots`: pruned to 24h per user.
- `user_notifications`: kept; one row per user/event.
- `user_campaign_starts`: deleted after a successful digest; failed sends stay
  for the next scan; orphan rows pruned.
- `user_campaign_completions`: retained; completion is permanent for the account.
- `user_watch_focus`: one row per user; updated in place.
- `user_sessions`: expired rows pruned at startup and during the scan job.
- `scan_runs`: shared, kept (small).

## Migration

No Alembic. `init_db()` calls `create_all` (new tables are additive), then both
the API and worker call `run_multi_user_migration()`. SQLite's write lock
serializes them; the first process sets the flag.

1. Open one transaction with `BEGIN IMMEDIATE` semantics and check
   `app_meta['multi_user_v1']` inside it. If set, commit and return.
2. If legacy `twitch_auth` exists with a row:
   - Require a non-empty `user_id`. If empty, abort with a clear operator error:
     fix the legacy row's `user_id`/`login` (or restore the backup and correct
     it), then restart. `OWNER_TWITCH_ID` only bootstraps an install with **no**
     legacy token; it cannot repair an empty legacy row. Do not guess an owner.
   - If `users` is empty, create the owner (`admin`, active) from the legacy
     `user_id`/`login` and profile.
   - If `users` is non-empty, require a matching `twitch_user_id`; otherwise
     abort rather than attach data to the wrong account.
   - Copy the token into `twitch_accounts` with `INSERT OR IGNORE`; set
     `reconnect_required` when `expires_at` is in the past.
   - Seed `telegram_chat_id` from `TELEGRAM_CHAT_ID` and enable it when present.
3. Copy `drop_progress`, `progress_snapshots`, `campaign_completions`,
   `watch_focus`, `notifications`, and `campaign_starts` into their `user_*`
   counterparts with `INSERT OR IGNORE`/upserts.
4. Copy `games.selected = true` rows into `user_games`. Mark a migrated owner
   `games_seeded=true` (the legacy selection, including an empty one, is
   authoritative). A placeholder `OWNER_TWITCH_ID` user stays `false` so its
   first connect seeds defaults.
5. Set `app_meta['multi_user_v1']` and commit in the same transaction.

If there is no legacy token:

- With `OWNER_TWITCH_ID` set and `users` empty, create a placeholder admin user
  with that Twitch id and no token. Connecting that Twitch account claims the
  row and its data.
- Otherwise the first person to connect becomes admin. Set `OWNER_TWITCH_ID`
  before going live if the owner identity matters.

Legacy tables are frozen after migration. The old owner signs in once; the
matching `twitch_user_id` resolves to the migrated row and their progress.

## Rollback / backup

**Backup before deploying** with the WAL-safe `sqlite3 .backup` procedure in
[OPERATIONS.md](OPERATIONS.md) (not a live file copy), verify the copy opens, and
keep it until the soak period ends.

**Rollback:** the previous release reads/writes the frozen legacy tables, so any
data written after migration is invisible to it. A rollback that must keep
post-upgrade data requires restoring the pre-upgrade backup. New tables are
additive, so an older release can ignore them, but do not downgrade the DB
schema without a backup.

## Backup / restore

With the container running:

```bash
docker exec twitch-drops-manager-api-1 python - <<'PY'
import sqlite3
src = sqlite3.connect('/data/drops.db')
dst = sqlite3.connect('/data/backup.db')
src.backup(dst)
dst.close(); src.close()
PY
docker cp twitch-drops-manager-api-1:/data/backup.db ./drops-backup.db
docker exec twitch-drops-manager-api-1 rm -f /data/backup.db
```

Restore into a stopped stack by replacing `/data/drops.db` in the
`twitch-drops-manager_drops_data` volume (keep a copy of the current file first).
The SQLite backup API produces a consistent copy; do not copy a live file without
WAL.
