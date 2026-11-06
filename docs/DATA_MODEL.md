# Data model

SQLite database at `/data/drops.db` inside the `drops_data` Docker volume
(local dev default: `./data/drops.db`). SQLAlchemy async + `aiosqlite`, WAL mode,
`foreign_keys=ON`, `synchronous=NORMAL`, 5s busy timeout.

## Tables

### `games`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | string, unique | upsert key |
| `box_art_url` | string | |
| `twitch_game_id` | string, indexed, nullable | Helix game id |
| `selected` | bool | whitelist; only selected games are scanned/tracked |
| `created_at`, `updated_at` | datetime | |

### `campaigns`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `external_id` | string, unique, indexed | `"{game name}:{provider campaign id}"` |
| `game_id` | FK → games, indexed, cascade | |
| `name` | string | |
| `status` | string, indexed | `ACTIVE`, `UPCOMING`, … |
| `starts_at`, `ends_at` | string, nullable | provider ISO strings |
| `details_url`, `owner_name` | string | |
| `allow` | JSON, nullable | channel allowlist from provider |
| `raw` | JSON, **deferred** | full provider payload; written by scans, never read by API |
| `created_at`, `updated_at` | datetime | |

Relationships: `game` (selectin), `rewards` (selectin, delete-orphan). Raw is
deferred to avoid loading ~715 KB on read paths.

### `rewards`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `campaign_id` | FK → campaigns, indexed, cascade | |
| `name` | string | drop/reward name |
| `benefit_name` | string | benefit description |
| `required_minutes` | int | |

### `streams`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_login` | string, indexed | |
| `user_name` | string | |
| `game_id` | FK → games, indexed, cascade | |
| `title` | text | |
| `viewers` | int | |
| `language` | string | |
| `started_at` | string, nullable | |
| `url` | string | |
| `live` | bool | |
| `created_at`, `updated_at` | datetime | |

Unique: `(user_login, game_id)`. Replaced wholesale each scan.

### `stream_campaign_matches`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `stream_id` | FK → streams, indexed, cascade | |
| `campaign_id` | FK → campaigns, indexed, cascade | |
| `eligibility` | string | explanatory text |

Unique: `(stream_id, campaign_id)`. Replaced wholesale each scan.

### `notifications`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `dedupe_key` | string, unique, indexed | event identity |
| `sent_at` | datetime | |

Keys in use:

- `drop-ready:{drop_id}`
- `campaign-ending:{campaign_gql_id}:24h`
- `campaign-ending:{campaign_gql_id}:2h`
- `campaign-started:{campaign_external_id}` for campaign-start digests
- `watch-offline:{campaign_id}:{user_login}:{focused_at}` for focused-live
  offline alerts (one per online session)
- `watch-complete:{campaign_id}` for focused campaign completion

New live streams are not sent to Telegram and have no notification key.

`NotificationRepository.claim()` inserts inside a SAVEPOINT; the unique constraint
makes cross-process dedupe atomic. `release()` removes a claim after a send failure.

### `campaign_starts`

Pending campaign-start events for **selected** games. A row is created when a
campaign transitions from a non-`ACTIVE` status to `ACTIVE` (new campaign,
`UPCOMING` → `ACTIVE`, or a new campaign after the previous one ended). The row is
deleted after a successful Telegram digest; if the send fails, it stays for the
next scan to retry.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `external_id` | string, unique, indexed | campaign identity (`"{game}:{gql_id}"`) |
| `detected_at` | datetime | first time the start was observed |

The matching `notifications` claim uses the key
`campaign-started:{campaign_external_id}`. Orphan rows are removed when their
campaign no longer exists in the catalog.

### `twitch_auth`

Single-row token store (no user accounts).

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | string | Twitch numeric id |
| `login` | string | |
| `access_token` | text | **secret**, plaintext in SQLite |
| `refresh_token` | text | empty for legacy implicit tokens |
| `expires_at` | datetime, nullable | null = no known expiry |
| `updated_at` | datetime | last save/refresh |

### `twitch_profile`

Profile cache read by `/twitch/status`; separate table so `create_all` can add it
to existing databases without ALTER TABLE.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | string, unique, indexed | |
| `display_name` | string | |
| `profile_image_url` | string | |
| `connected_at` | datetime, nullable | set on connect / first profile save |
| `updated_at` | datetime | |

### `drop_progress`

Latest inventory snapshot (replaced each progress sync).

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `drop_id` | string, unique, indexed | Twitch drop id |
| `drop_name` | string | |
| `drop_instance_id` | string, nullable | |
| `campaign_gql_id` | string, indexed | Twitch campaign id |
| `campaign_name` | string | |
| `campaign_ends_at` | string, nullable | |
| `game_name`, `game_box_art_url` | string | |
| `starts_at`, `ends_at` | string, nullable | drop window |
| `required_minutes`, `current_minutes` | int | |
| `is_claimed`, `is_ready` | bool | |
| `benefits` | JSON list | |
| `updated_at` | datetime | |

### `progress_snapshots`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `drop_id` | string, indexed | |
| `current_minutes` | int | |
| `recorded_at` | datetime | |

Composite index `ix_progress_snapshots_drop_recorded (drop_id, recorded_at)`.
Pruned to the last 24h on every progress sync. Used for the watch rate.

### `watch_focus`

Singleton focus pointer for the queue watcher. The table is keyed by `id=1`;
focused mode allows **one** watcher. It stores a copy of the focused stream and
campaign so the UI can render the target without a join. It is not a playback
controller and contains no watch heartbeats.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | always `1` |
| `enabled` | bool | focused mode on/off |
| `status` | string | `idle`, `focused`, `offline`, `waiting` |
| `reason` | string | `manual`, `auto`, `live`, `offline`, `completed`, … |
| `stream_id` | int, nullable | current Twitch stream row (recreated each scan) |
| `user_login`, `user_name`, `stream_url`, `stream_title` | string | focused channel snapshot |
| `game_name`, `game_box_art_url` | string | |
| `campaign_id` | string | Twitch GQL campaign id from `drop_progress` |
| `campaign_name` | string | |
| `target_minutes` | int | remaining campaign watch minutes at focus time |
| `ends_at` | string, nullable | campaign end |
| `focused_at`, `updated_at` | datetime | |

The worker matches the stored focus by `user_login` + `campaign_id` first (stream
ids are replaced each scan), then falls back to `stream_id`.

### `scan_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `started_at`, `finished_at` | datetime | |
| `ok` | bool | |
| `error` | text, nullable | |
| `campaign_count`, `stream_count` | int | |

## Relationships at a glance

```
games 1─* campaigns 1─* rewards
games 1─* streams 1─* stream_campaign_matches *─1 campaigns
twitch_auth (1 row)     twitch_profile (1 row)
drop_progress (current) 1─* progress_snapshots (history)
notifications (dedupe ledger)
campaign_starts (pending start events)
watch_focus (1 row, queue focus pointer)
scan_runs (audit)
```

`drop_progress` is deliberately not FK-linked to `campaigns`: inventory campaign
ids come from Twitch GQL and may not exist in the public catalog. Matching is done
by the `external_id` suffix (`"{game}:{gql_id}"`).

## Retention / replacement

- `streams` and `stream_campaign_matches`: replaced on every scan.
- `campaigns`/`rewards`: upserted; stale campaigns deleted when absent from the
  current catalog.
- `drop_progress`: replaced on every progress sync.
- `progress_snapshots`: pruned to 24h.
- `notifications`: kept; one row per event forever (small).
- `campaign_starts`: deleted after a successful digest; failed sends stay for the
  next scan; orphan rows pruned on every scan.
- `watch_focus`: single row; updated in place by the API/worker.
- `scan_runs`: kept (small); could be pruned in the future.

## Migrations

No Alembic. `init_db()` calls `create_all`; new tables are created automatically.
Missing indexes on existing tables are created with `checkfirst=True`. Column
changes to existing tables require a manual migration or a new side table (see
`twitch_profile` as the pattern).

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
