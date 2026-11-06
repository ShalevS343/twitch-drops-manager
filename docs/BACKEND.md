# Backend

FastAPI + asynchronous SQLAlchemy + APScheduler. Python 3.10+ (3.12 in the
container). Source lives in `backend/app`.

## Layout

```
app/
  main.py                 FastAPI app, lifespan, init_db, profile warm-up
  api/
    deps.py               session/service/provider dependencies
    v1/
      health.py status.py games.py campaigns.py streams.py
      scans.py notifications.py progress.py watch_queue.py router.py
  core/
    config.py             pydantic-settings env configuration
    db.py                 async engine, session factory, SQLite pragmas, init_db
    exceptions.py         ProviderError / NotConfiguredError
    logging.py            logging config (httpx/httpcore quieted)
    security.py           optional X-API-Token guard
  domain/
    models.py             SQLAlchemy models
    schemas.py            Pydantic response/request models
    parsing.py            catalog + inventory parsing, date helpers
  providers/
    sunkwi.py             public Drops catalog
    twitch.py             Helix app-token client (streams)
    twitch_user.py        Twitch user OAuth + internal GQL (inventory/profile)
    telegram.py           Bot API send
  repositories/
    campaigns.py games.py streams.py notifications.py progress.py
    campaign_starts.py scans.py twitch_auth.py twitch_profile.py
  services/
    scan_service.py       catalog + streams + campaign-start alerts
    progress_service.py   inventory + snapshots + ready/deadline alerts
    progress_metrics.py   remaining-time and watch-rate calculations
    factory.py            cached providers + service builders
  worker/scheduler.py     APScheduler worker entry point
tests/                    pytest suite (58 tests)
```

## Startup (`main.py`)

1. `configure_logging()` — note: `httpx`/`httpcore` are set to `WARNING` so request
   URLs (and the Telegram bot token) are not logged.
2. `init_db()` — creates tables, then creates any missing model indexes with
   `checkfirst=True` (safe on existing SQLite databases).
3. `start_profile_refresh_warmup()` — launches a non-blocking check; if
   `twitch_auth` exists but `twitch_profile` does not, it schedules a background
   profile fetch.
4. App serves `/api/v1`; on shutdown, background profile tasks are cancelled and
   the engine is disposed.

## Configuration

`app/core/config.py` (pydantic-settings, reads `.env` / `../.env`):

| Field | Default | Notes |
|---|---|---|
| `database_url` | `sqlite+aiosqlite:///./data/drops.db` | Compose sets `/data/drops.db` |
| `api_token` | empty | If set, mutating endpoints require `X-API-Token` |
| `cors_origins` | `http://localhost:5173` | Comma-separated |
| `sunkwi_url` | `https://drops.sunkwi.com/api/twitch/drops` | Catalog endpoint |
| `drops_api_key` | empty | Optional; also controls cache TTL defaults |
| `twitch_client_id` / `secret` | empty | Helix app credentials |
| `twitch_gql_url` | `https://gql.twitch.tv/gql` | Internal GQL |
| `twitch_gql_client_id` | empty | Advanced override |
| `twitch_device_client_id` | empty → built-in first-party client | Progress login + GQL client id |
| `twitch_device_client_secret` | empty | Advanced |
| `twitch_oauth_redirect_uri` | `https://www.twitch.tv/` | Implicit grant redirect |
| `telegram_bot_token` / `chat_id` | empty | Notifications |
| `poll_seconds` | 900 | Scan interval, min `min_poll_seconds` |
| `progress_poll_seconds` | 300 | Progress interval, min `min_progress_poll_seconds` |
| `default_games` | `Rust,Minecraft` | First-run whitelist |

See [OPERATIONS.md](OPERATIONS.md) for the deployment-facing list.

## Scan service

`ScanService.run()`:

1. `SunkwiProvider.fetch_games()` — 20s timeout; on 429/5xx/timeout returns the
   cache; `429` without cache raises `ProviderError` with the retry window.
2. Upsert games; on the very first run, select `DEFAULT_GAMES`.
3. Parse campaigns for selected games; capture the previous status of every
   campaign, then upsert campaigns + rewards and delete stale campaigns.
4. For selected games, record a `campaign_starts` row when a campaign's status
   changes to `ACTIVE` from anything else (`UPCOMING`, `ENDED`, or no prior row).
   This covers games with no current campaign and the next campaign after one
   ended. Orphan pending rows are pruned.
5. Discover streams via Helix for each selected game with a Twitch game id.
6. Match streams to active campaigns using `allow` (channel allowlist when
   `isEnabled`).
7. Replace the `streams`/`stream_campaign_matches` tables.
8. Notify in one digest:
   - pending campaign starts for selected games;
   - live streams (when `drop_progress` has rows, only streams matching an
     in-progress campaign; otherwise all selected-game matches).
   Each event is claimed atomically (`campaign-started:*` or
   `{user_login}:{game_id}`). On Telegram failure all claims are released and
   pending starts remain for the next scan; on success start rows are deleted.
9. Write a `ScanRun` (`ok`, error, counts).

## Progress service

`ProgressService.run()`:

1. Load `twitch_auth`; no auth → disconnected result.
2. `_ensure_token`: if a known expiry is within 5 minutes, refresh with the stored
   refresh token; if the token has no expiry, use it. A refresh failure raises
   `NotConfiguredError` (UI prompts reconnect).
3. `TwitchUserProvider.fetch_inventory()` → GQL `Inventory` persisted query; if
   Twitch returns `PersistedQueryNotFound`, retry with the raw query.
4. Flatten `dropCampaignsInProgress` with `parse_inventory` (current/required
   minutes, claimed, benefits, campaign/game metadata).
5. `ProgressRepository.replace(rows)`; commit.
6. Insert one `ProgressSnapshot` per drop; prune >24h.
7. Build notifications:
   - ready drops (`is_ready` and not claimed) keyed `drop-ready:<drop_id>`
   - deadline: tightest window only, `campaign-ending:<gql_id>:2h` or `:24h`
   - atomically claim each key before sending; one digest; release on failure.
8. Commit; return counts.

### Remaining-time / watch-rate math (`progress_metrics.py`)

- `remaining_minutes = max(0, required - current)` (claimed → 0).
- Rate uses snapshots from the last **2 hours**: oldest vs newest, requires at
  least 5 minutes span; `rate = delta_minutes * 60 / span_minutes`.
- Rate below `0.5` min/hour → `null` (not actually watching).
- Campaign remaining = sum of unclaimed drops. There is no ETA field: the UI
  shows remaining minutes only.

## Watch queue

`GET /watch-queue` (see `api/v1/watch_queue.py`):

- Load `drop_progress` + snapshots.
- One flat SQL join for streams → matches → campaigns → games (no full ORM
  campaign/reward loading).
- Keep only campaigns whose GQL id is in progress; dedupe campaigns by
  `external_id`; prefer `DropProgress` name/end date, fall back to `campaigns`.
- Sort by earliest campaign end, then most remaining work, then viewers.
- Next drop = unclaimed drop with the smallest positive remaining minutes.

## Providers

### Sunkwi (`sunkwi.py`)

- Optional `X-API-Key`.
- In-memory cache; persists successful payloads to
  `<sqlite-dir>/sunkwi_cache.json` (atomic replace).
- Honors `X-RateLimit-Reset` / `Retry-After` after success and on 429; serves stale
  cache on 429/5xx/timeouts/invalid payloads.
- The provider window is currently **1 request / 300s**.

### Twitch Helix (`twitch.py`)

- Client-credentials token, cached until near expiry.
- `GET /helix/streams` with pagination (up to 5 pages, 100 per page).
- 401 → refresh token and retry once.

### Twitch user (`twitch_user.py`)

- Progress login uses Twitch's **implicit grant** URL (`authorize_url`) with a
  first-party public client; the user pastes the redirect URL.
- `parse_oauth_token` accepts a full URL with `#access_token=` or a raw token.
- `validate` uses `/oauth2/validate`.
- `fetch_inventory` uses the internal GQL `Inventory` persisted query with a raw
  fallback.
- `fetch_profile` uses `ViewerCard` (`displayName`, `profileImageURL(width:300)`),
  cached in memory for 10 minutes; the persisted profile lives in `twitch_profile`.
- Sends Android client headers (`User-Agent`, `Client-Session-Id`, `X-Device-Id`,
  `Origin`, `Referer`) because GQL rejects third-party-app tokens.
- **Read-only**: no claim mutations, no watch heartbeats.

### Telegram (`telegram.py`)

- `sendMessage` with previews disabled.
- Notification policy: atomic claim + one digest per run; no claim if Telegram is
  unconfigured; failed send releases claims.

## Data access

Repositories wrap SQLAlchemy. Notable choices:

- `Campaign.raw` is `deferred=True` — it is written during scans and never read on
  API paths (715 KB in a real dataset).
- `CampaignRepository.list_all()` is **not** used on read paths; watch queue uses a
  flat query.
- `NotificationRepository.claim()` inserts inside a SAVEPOINT and catches
  `IntegrityError`; `release()` deletes a claim after a failed send.
- `ProgressRepository` replaces `drop_progress` wholesale each sync (the inventory
  is the full current state) and manages snapshots.

## Tests

`backend/tests` (58 tests):

- parsing/inventory
- scan service (catalog, streams, scoped alerts, campaign starts, retry)
- progress service (watch rate, digests, deadline windows, retry)
- notifications (claim/release/duplicate)
- watch queue (filtering/sorting/next drop)
- streams API, status API, DB/index creation, models (deferred raw)

Run:

```bash
cd backend
PYTHONPATH=$PWD pytest -q
ruff check app tests
```

## Adding a backend feature

1. Add/modify models in `domain/models.py` with indexes for new query patterns.
2. Add Pydantic contracts in `domain/schemas.py` (additive where possible).
3. Put query logic in `repositories/`; orchestration in `services/`.
4. Add endpoint in `api/v1/` and register in `router.py`.
5. Add tests; update [API.md](API.md), [DATA_MODEL.md](DATA_MODEL.md),
   [BACKEND.md](BACKEND.md), [STATUS.md](STATUS.md), [CHANGELOG.md](CHANGELOG.md).
6. Use explicit loaders/flat joins for read paths; avoid `selectin` graphs for
   ID/name mappings.

## Known limitations

- Single uvicorn worker; a heavy request can serialize others (P1 work).
- SQLite writes are serialized; fine for one user.
- Twitch GQL is unofficial and can change without notice.
- Legacy implicit tokens can have `expires_at = null` (no refresh).
- Manual `POST /scans` is synchronous (~2–3s).
