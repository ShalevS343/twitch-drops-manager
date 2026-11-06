# Architecture

## Purpose

A single-user, self-hosted Twitch Drops dashboard. It answers three questions:

1. Which campaigns and rewards are currently available?
2. Which live streams can advance my open drops?
3. How far along is my account on each drop, and what needs attention?

It is deliberately **read-only** toward Twitch rewards. It never claims drops and
never automates watching.

## Non-goals

- Multi-tenant user accounts or per-user isolation.
- Automatic claiming or watch-time farming (violates Twitch ToS).
- Real-time (sub-minute) progress; the worker is interval-based.
- Horizontal scaling; the deployment target is one Raspberry Pi.

## Runtime topology

```
                         Tailnet / LAN
                              │
                        nginx :8282
                    ┌─────────┴─────────┐
                    │                   │
             static React SPA     /api/ reverse proxy
                                        │
                                   FastAPI :8000
                                        │
                             ┌──────────┴──────────┐
                             │                     │
                     SQLite /data/drops.db   (reads/writes)
                             │                     │
                     worker (APScheduler) ─────────┘
                             │
        ┌────────────────────┼─────────────────────┐
        │                    │                     │
  Sunkwi Drops API     Twitch Helix          Twitch GQL
  (catalog)            (app token)           (user token)
        │                    │                     │
        └────────────────────┴─────────────────────┘
                             │
                       Telegram Bot API
```

- **`frontend`** — nginx serving the Vite build; gzip + immutable hashed assets;
  proxies `/api/` to `api:8000` with HTTP/1.1 keepalive.
- **`api`** — FastAPI application (`uvicorn app.main:app`). Serves all read/write
  endpoints. One uvicorn worker.
- **`worker`** — same backend image, `python -m app.worker.scheduler`. Runs the
  scan and progress jobs with APScheduler.
- **SQLite** — named Docker volume `twitch-drops-manager_drops_data`, mounted at
  `/data`; database at `/data/drops.db` with WAL mode.
- **Kuma** — optional external Uptime Kuma + `kuma-sync`; the compose labels
  create TCP monitors for 8282 and 8000.
- **Homepage** — optional labels for the local Homepage dashboard.

Ports: UI `8282`, API `8000` (both published on the host).

## Components

### Backend API (`backend/app/api/v1`)

Read endpoints are public on the LAN/tailnet; mutating endpoints optionally require
`X-API-Token` when `API_TOKEN` is set. See [API.md](API.md).

- `/status`, `/health` — system summary and health.
- `/games`, `/campaigns`, `/streams` — catalog/stream reads.
- `/progress`, `/watch-queue` — personal progress + actionable queue.
- `/twitch/*` — connection status, implicit-login URL, token acceptance, logout.
- `/scans`, `/notifications/test`, `/progress/refresh` — manual actions.

### Worker (`backend/app/worker/scheduler.py`)

Two interval jobs:

- **Scan** every `POLL_SECONDS` (default 900s, min 300s): fetch the public catalog,
  sync games/campaigns/rewards, fetch Twitch live streams for selected games,
  match streams to campaigns, send stream alerts.
- **Progress** every `PROGRESS_POLL_SECONDS` (default 300s, min 60s): refresh the
  user token if needed, fetch the Twitch inventory, replace `drop_progress`,
  insert rate snapshots, send ready/deadline digests.

Both jobs also run once at startup.

### Providers (`backend/app/providers`)

| Provider | Credentials | Purpose | Failure behavior |
|---|---|---|---|
| `SunkwiProvider` | `DROPS_API_KEY` (optional) | Public campaign catalog | In-memory + disk cache (`/data/sunkwi_cache.json`); serves stale on 429/5xx/timeout; honors rate-limit reset |
| `TwitchProvider` | `TWITCH_CLIENT_ID`/`SECRET` | Helix streams (app token) | Scan falls back to no new streams; scan run marked failed if no credentials |
| `TwitchUserProvider` | Twitch user token (`twitch_auth`) | Internal GQL `Inventory` + `ViewerCard` | 401 → reconnect; token refreshed when expiry exists; profile warm-up is non-blocking |
| `TelegramProvider` | `TELEGRAM_BOT_TOKEN`/`CHAT_ID` | Notifications | Logged warning; claim released so the next run can retry |

### Data layer

SQLAlchemy async + `aiosqlite`. Repositories isolate query logic. Tables are
created with `Base.metadata.create_all`; missing indexes are created with
`checkfirst=True` for existing databases (no Alembic). See
[DATA_MODEL.md](DATA_MODEL.md).

### Frontend (`frontend/src`)

React 18 + TypeScript + Vite + TanStack Query. No router dependency: seven tabs
are hash routes (`#/overview`, `#/campaigns`, `#/progress`, `#/watch-queue`,
`#/streams`, `#/settings`, `#/profile`). See [FRONTEND.md](FRONTEND.md).

## Data flows

### Catalog scan

1. `SunkwiProvider.fetch_games()` returns the cached/fresh catalog (1 req/300s).
2. Games are upserted; first run selects `DEFAULT_GAMES`.
3. Campaigns + rewards are upserted for the selected whitelist; stale campaigns
   are deleted.
4. For each selected game with a Twitch game id, Helix returns live streams.
5. Streams are matched to active campaigns (respecting channel allowlists) and
   inserted; old stream rows are replaced.
6. New eligible streams are claimed/deduped and sent as **one Telegram digest**.
7. A `ScanRun` row records counts and errors.

### Progress sync

1. Read `twitch_auth`; if no user token, return disconnected.
2. Refresh the token if an expiry is known and near; otherwise use it as-is.
3. Query Twitch GQL `Inventory` (`dropCampaignsInProgress`).
4. Flatten campaigns/drops into `drop_progress` rows (replacing the previous set).
5. Insert `progress_snapshots`; prune older than 24h.
6. Compute the watch rate from snapshots in the last 2h.
7. Build one digest of newly ready drops and 24h/2h deadline reminders; atomically
   claim each dedupe key before sending; release claims on failure.

### API read path

- `/progress` reads `drop_progress` + `progress_snapshots` and computes metrics.
- `/watch-queue` uses a lightweight campaign mapping and **one flat join** across
  streams, matches, campaigns, and games (P0 optimization).
- `/streams` uses one flat join returning stream + game + campaign names.
- `/status` runs a small set of counts plus auth/scan/profile state.
- `/twitch/status` is DB-only when a profile row exists; it schedules a background
  GQL refresh on a cold profile instead of blocking the request.

## Design constraints

- **Read-only** toward Twitch rewards; no claiming, no watching automation.
- **No user table**; only the OAuth token and a small profile cache are persisted.
- **Single writer**: SQLite WAL, one worker process; keep writes short.
- **No external queue**: APScheduler in the worker; idempotent upserts where
  possible.
- **Provider volatility**: Twitch's internal GQL can change; the `Inventory`
  persisted hash has a raw-query fallback. Twitch may invalidate the first-party
  client id; it is configurable.

## Failure modes and behavior

| Failure | Behavior |
|---|---|
| Sunkwi 429/5xx/timeout | Serve last catalog from memory/disk; log; scan still succeeds |
| Sunkwi cold + 429 | `ProviderError` with retry hint; scan marked failed until cache exists |
| Twitch app token missing | Scan raises `NotConfiguredError`; status shows `twitch_configured=false` |
| Twitch user token invalid/expired | `/progress/refresh` returns 400; UI prompts reconnect |
| Twitch GQL profile fails | Keep login-only profile; no request failure; profile retry policy on reconnect |
| Telegram send fails | Release claims; next run retries; no duplicate if claim succeeded |
| SQLite locked | WAL + busy timeout; requests may briefly retry |
| Portainer redeploy | Named volume persists; `create_all` adds new tables/indexes |

## Security model

- LAN/tailnet deployment; optional API token for writes.
- Twitch token stored plaintext in SQLite; protect the volume and host.
- Telegram bot token in `.env`; rotate if leaked.
- The app never stores Twitch passwords; login is Twitch's implicit grant.
- No auto-claim/watch automation.
