# Architecture

## Purpose

A small, self-hosted Twitch Drops dashboard for a group of friends. Each person
signs in with their own Twitch account and sees their own progress; the catalog
and live streams are shared. It answers three questions:

1. Which campaigns and rewards are currently available?
2. Which live streams can advance my open drops?
3. How far along is my account on each drop, and what needs attention?

It is deliberately **read-only** toward Twitch rewards. It never claims drops and
never automates watching.

## Non-goals

- Passwords, email accounts, password reset, or open signup.
- Per-user Twitch client credentials; one first-party client serves the shared
  read-only GQL inventory.
- Letting one user see another's progress, games, focus, or Telegram destination.
- Real-time (sub-minute) progress; the worker is interval-based.
- Horizontal scaling, Postgres, Redis, or a separate job queue in this phase.
- Automatic claiming or watch-time farming (violates Twitch ToS).

## Runtime topology

```
                         Tailnet / LAN / Tailscale Funnel
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
                               SQLite /data/drops.db   sessions + users
                                       │                     │
                               worker (APScheduler) ────────┘
                                       │
              ┌────────────────────────┼─────────────────────┐
              │                        │                     │
        Sunkwi Drops API         Twitch Helix          Twitch GQL
        (shared catalog)         (app token)          (per-user tokens)
              │                        │                     │
              └────────────────────────┴─────────────────────┘
                                       │
                              Telegram Bot API
                            (each user's chat id)
```

- **`frontend`** — nginx serving the Vite build; gzip + immutable hashed assets;
  proxies `/api/` to `api:8000` with HTTP/1.1 keepalive. It preserves the inbound
  `X-Forwarded-Proto` (falling back to `$scheme`) so HTTPS behind Tailscale
  Funnel marks session cookies `Secure`. There is no shared basic-auth prompt;
  the app's Twitch login and invite code are the access gate.
- **`api`** — FastAPI application (`uvicorn app.main:app`). Serves auth, the
  session-scoped app endpoints, and admin endpoints. One uvicorn worker.
- **`worker`** — same backend image, `python -m app.worker.scheduler`. Scans the
  shared catalog once, then loops per active user for progress and focus.
- **SQLite** — named Docker volume `twitch-drops-manager_drops_data`, mounted at
  `/data`; `/data/drops.db` in WAL mode.
- **Kuma / Homepage** — optional external monitoring/dashboard labels.

Ports: UI `8282`, API `127.0.0.1:8000` (loopback only; nginx reaches it over the
Compose network).

## Components

### Authentication and sessions

- Twitch is the only identity provider. There are no passwords.
- `POST /auth/twitch/connect` validates the pasted implicit-grant token with
  Twitch, maps it to `users.twitch_user_id`, and creates/loads the local user.
- The first user is `admin`; later users need `REGISTRATION_CODE` unless
  `REGISTRATION_OPEN=true`. An empty code means closed, never open.
- A successful connect creates an opaque session token, stores only its SHA-256
  hash in `user_sessions`, and sets:
  - `tdm_session` — `HttpOnly`, `SameSite=Lax`, `Path=/`, absolute
    `SESSION_TTL_DAYS` expiry.
  - `tdm_csrf` — readable token echoed as `X-CSRF-Token` on unsafe methods and
    compared with `secrets.compare_digest`.
- `SESSION_COOKIE_SECURE=auto` derives `Secure` from `X-Forwarded-Proto`.
- When `PUBLIC_ORIGIN`/`ALLOWED_HOSTS` are set, they pin production origin/host
  checks; the same-origin fallback is for local development.
- Disabled users cannot log in; disabling deletes their sessions and stops their
  focus.

### Backend API (`backend/app/api/v1`)

Every app endpoint requires a session except `/health` and the public auth
endpoints (`/auth/me`, `/auth/twitch/authorize`, `/auth/twitch/connect`). See
[API.md](API.md).

- `/auth/*` — sign in, `/auth/me`, logout, Telegram settings, disconnect.
- `/status`, `/health` — summary and health.
- `/games`, `/campaigns`, `/streams` — catalog reads scoped to the current
  user's games/completions.
- `/progress`, `/watch-queue` — current user's progress + actionable queue.
- `/watcher` — current user's single focused watcher (focus pointer only).
- `/twitch/status` — current user's connection, profile, sync health.
- `/notifications/test` — send to the current user's chat.
- `/scans`, `/admin/users` — admin-only global scan and user management.
- `/progress/refresh` — sync the current user.

### Worker (`backend/app/worker/scheduler.py`)

Intervals stay the same; each job isolates failures per user so one bad token
does not stop everyone.

- **Scan** every `POLL_SECONDS` (default 900s, min 300s):
  1. Fetch/upsert the shared catalog.
  2. Compute the union of selected games across active users.
  3. Discover live streams once for that union and replace shared stream rows.
  4. For each campaign transitioning to `ACTIVE`, create
     `user_campaign_starts` rows only for users tracking that game **and**
     Telegram-enabled with a chat id.
  5. Send each opted-in user their own start digest to their chat id, claiming
     `user_notifications` first and deleting that user's start row on success.
  6. Prune expired sessions.
- **Progress** every `PROGRESS_POLL_SECONDS` (default 300s, min 60s): loop over
  users with a Twitch account, one fresh session per user. Skip users marked
  `reconnect_required`; otherwise fetch inventory with that user's token, replace
  only their `user_drop_progress`/snapshots, update completions, and send
  ready/deadline digests to that user's chat. On success record
  `last_synced_at`, clear `reconnect_required`/`last_error`; on a user-token
  401/expiry set `reconnect_required` + `last_error`. Log and continue on
  failure. There is no refresh-token path.
- **Watcher reconcile** every `WATCHER_POLL_SECONDS` (default 60s, min 30s):
  loop over users with focus enabled; reconcile each against their own queue and
  notify only that user. It does not auto-move or control playback.
- **Profile warm-up**: no singleton startup path. Fetch the profile on connect;
  if `/twitch/status` finds an empty profile, schedule one background refresh for
  that user id only.

The worker remains sequential. With dozens of users this is simpler and safer for
SQLite than parallel writers.

### Providers (`backend/app/providers`)

| Provider | Credentials | Purpose | Failure behavior |
|---|---|---|---|
| `SunkwiProvider` | `DROPS_API_KEY` (optional) | Shared campaign catalog | In-memory + disk cache (`/data/sunkwi_cache.json`); serves stale on 429/5xx/timeout; honors rate-limit reset |
| `TwitchProvider` | `TWITCH_CLIENT_ID`/`SECRET` | Shared Helix streams (app token) | Scan falls back to no new streams; scan run marked failed if no credentials |
| `TwitchUserProvider` | Per-user token (`twitch_accounts`) | Internal GQL `Inventory` + `ViewerCard` | User 401/expiry → set `reconnect_required` and skip; profile refresh is non-blocking |
| `TelegramProvider` | `TELEGRAM_BOT_TOKEN` + per-user chat id | Notifications | Logged warning with token/URL redacted; claim released so the next run can retry |

### Data layer

SQLAlchemy async + `aiosqlite`. Repositories isolate query logic and personal
repositories take `user_id`. Tables are created with
`Base.metadata.create_all`; the one-time multi-user migration copies legacy rows
into user-keyed tables in a single transaction. See
[DATA_MODEL.md](DATA_MODEL.md).

### Frontend (`frontend/src`)

React 18 + TypeScript + Vite + TanStack Query. No router dependency: seven tabs
are hash routes (`#/overview`, `#/campaigns`, `#/progress`, `#/watch-queue`,
`#/streams`, `#/settings`, `#/profile`). An `AuthGate` wraps the dashboard and
shows the Twitch sign-in screen without a session. Query keys include the user
id, and logout/user change clears the query cache. See [FRONTEND.md](FRONTEND.md).

## Data flows

### Sign-in

1. `GET /auth/me` → no session → `AuthGate` renders the sign-in screen.
2. `GET /auth/twitch/authorize` → authorize URL.
3. The user authorizes and pastes the redirect URL (+ invite code for a new
   account).
4. Backend validates with Twitch, maps/creates the user, stores the token,
   creates the session, sets cookies, and refreshes the profile.
5. The SPA refreshes `/auth/me` and loads all data for that user.

### Catalog scan (shared, once)

1. `SunkwiProvider.fetch_games()` returns the cached/fresh catalog (1 req/300s).
2. Games are upserted; new users get `DEFAULT_GAMES` as their initial selection
   at connect.
3. Campaigns + rewards are upserted for the union of selected games; stale
   campaigns are deleted.
4. For each selected game with a Twitch game id, Helix returns live streams once.
5. Streams are matched to active campaigns (respecting allowlists) and replaced.
6. Campaign starts are queued/sent per opted-in user; new live streams are not
   sent to Telegram.
7. A shared `ScanRun` row records counts and errors.

### Progress sync (per user)

1. Load that user's `twitch_accounts`; no token → disconnected for that user.
2. Skip if `reconnect_required`; otherwise use the token as-is (no refresh).
3. Query Twitch GQL `Inventory` (`dropCampaignsInProgress` +
   `earnedDropRewards` with `fetchRewardCampaigns: true`).
4. Flatten into that user's `user_drop_progress` (replacing the previous set).
5. Persist `user_campaign_completions` for fully claimed campaigns.
6. Insert `user_progress_snapshots`; prune that user's rows older than 24h.
7. Compute the watch rate from that user's snapshots in the last 2h.
8. Build one digest per user of newly ready drops and 24h/2h deadline reminders;
   claim each `(user_id, dedupe_key)` before sending; release on failure.

### API read path

- `/progress` reads the current user's progress + snapshots and computes metrics.
- `/watch-queue` uses a lightweight campaign mapping and one flat join across
  streams, matches, campaigns, and games, filtered to that user's games.
- `/watcher` reuses the watch-queue builder for candidates and returns that
  user's focus row.
- `/streams` uses one flat join and filters against that user's completions.
- `/status` runs per-user counts plus shared scan/provider state.
- `/twitch/status` is DB-only when the user's profile exists; it schedules a
  background refresh on a cold profile.

## Design constraints

- **Read-only** toward Twitch rewards; no claiming, no watching automation.
- **Twitch-only identity**; no local passwords. Sessions and roles replace the
  retired `API_TOKEN`.
- **User-keyed schema**: personal tables carry `user_id`; catalog/streams are
  shared.
- **Single writer**: SQLite WAL, one worker process; keep writes short.
- **No external queue**: APScheduler in the worker; idempotent upserts where
  possible.
- **Provider volatility**: Twitch's internal GQL can change; the `Inventory`
  persisted hash has a raw-query fallback. Twitch may invalidate the first-party
  client id; it is configurable.
- **Legacy tables stay** until the rollback window passes.

## Failure modes and behavior

| Failure | Behavior |
|---|---|
| Invalid/expired session cookie | `401`; SPA returns to sign-in |
| Invalid/expired Twitch user token | Set `reconnect_required`; skip that user's sync until reconnect; UI shows reconnect |
| Global Twitch client misconfigured | Do not set per-user `reconnect_required`; surface the global error |
| One user's progress fetch fails | Log, store `last_error`, continue other users |
| Telegram send fails for one user | Release that user's claims; leave start rows for retry; redact token; others unaffected |
| User opts out of Telegram | Delete pending starts; no backlog if they opt back in |
| Registration code missing on a new account | `403` with a clear message |
| Too many auth attempts | `429` with retry guidance |
| Same browser tries a different Twitch account | `409`; sign out first |
| Browser switches users | All query caches cleared; no previous-user data rendered |
| Sunkwi 429/5xx/timeout | Serve last catalog from memory/disk; log; scan still succeeds |
| Migration sees an empty legacy `user_id` or conflicting user | Abort with an operator error; no guessing |
| Rollback to previous release | Legacy tables are frozen; restore the pre-upgrade backup to keep new data |
| SQLite locked | WAL + busy timeout; requests may briefly retry |
| Portainer redeploy | Named volume persists; `create_all` adds new tables/indexes |

## Security model

- Twitch-only login; no password surface or local recovery.
- Opaque server-side sessions; `HttpOnly` session cookie + CSRF header; absolute
  30-day expiry.
- `Secure` cookies on public HTTPS via preserved `X-Forwarded-Proto`;
  `PUBLIC_ORIGIN`/`ALLOWED_HOSTS` pin production origin/host checks.
- Auth endpoints are rate-limited per client IP (`AUTH_RATE_LIMIT_PER_MINUTE`).
- The public static UI is reachable without a shared password; personal API
  endpoints require a session, and new accounts require the invite code.
- Twitch tokens are plaintext in SQLite; protect the volume and host. Never log
  tokens. Telegram errors are redacted so the bot token never reaches logs.
- Each user can only read/write their own personal data; admins see only safe
  account metadata (never tokens or chat ids).
- No auto-claim/watch automation; the focused watcher is a queue pointer only.
