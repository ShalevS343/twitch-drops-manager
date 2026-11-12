# Backend

FastAPI + asynchronous SQLAlchemy + APScheduler. Python 3.10+ (3.12 in the
container). Source lives in `backend/app`.

## Layout

```
app/
  main.py                 FastAPI app, lifespan, init_db + migration, middleware
  api/
    deps.py               session/user dependencies (current user, admin)
    v1/
      auth.py admin.py health.py status.py games.py campaigns.py streams.py
      scans.py notifications.py progress.py watch_queue.py watcher.py router.py
  core/
    config.py             pydantic-settings env configuration
    db.py                 async engine, session factory, SQLite pragmas, init_db
    migrations.py         single-transaction multi-user data migration
    exceptions.py         ProviderError / NotConfiguredError / ReconnectRequiredError
    logging.py            logging config (httpx/httpcore quieted)
    security.py           sessions, CSRF, cookie helpers, role checks
    rate_limit.py         in-process auth attempt limiter
    middleware.py         CSRF, no-store, trusted-host middleware
  domain/
    models.py             users/sessions/twitch accounts/user_* + shared + legacy
    schemas.py            Pydantic response/request models
    parsing.py            catalog + inventory parsing, date helpers
  providers/
    sunkwi.py             public Drops catalog (shared)
    twitch.py             Helix app-token client (shared streams)
    twitch_user.py        per-user OAuth + internal GQL (inventory/profile)
    telegram.py           Bot API send to a specific chat
  repositories/
    users.py user_sessions.py twitch_accounts.py user_games.py
    progress.py campaign_completions.py notifications.py campaign_starts.py
    watch_focus.py campaigns.py games.py streams.py scans.py
  services/
    auth_service.py       connect/logout/disconnect/registration/Telegram settings
    profile_service.py    per-user profile refresh + warm-up
    scan_service.py       shared catalog + streams + per-user campaign starts
    progress_service.py   per-user inventory + snapshots + ready/deadline alerts
    progress_metrics.py   remaining-time and watch-rate calculations
    watch_queue_service.py  shared queue builder + candidate selection
    watch_focus_service.py  per-user focus state + offline/completion alerts
    factory.py            cached providers + service builders
  worker/scheduler.py     APScheduler worker entry point
tests/                    pytest suite (auth, isolation, migration, worker, …)
```

## Startup (`main.py`)

1. `configure_logging()` — `httpx`/`httpcore` are set to `WARNING` so request
   URLs (and the Telegram bot token) are not logged.
2. `init_db()` — creates tables, creates missing model indexes with
   `checkfirst=True`, then runs `run_multi_user_migration()`.
3. Middleware:
   - `TrustedHostMiddleware` when `ALLOWED_HOSTS` is set.
   - CSRF check on unsafe `/api/v1/*` methods when a session cookie exists
     (the public connect endpoint is exempt).
   - `Cache-Control: no-store` on authenticated API responses.
4. App serves `/api/v1`; on shutdown, background profile tasks are cancelled and
   the engine is disposed.

Both the API and worker call `init_db()`; SQLite's write lock serializes the
migration and `app_meta['multi_user_v1']` makes it idempotent. A migration abort
(empty legacy `user_id` or conflicting user) stops startup with an operator
error instead of guessing.

## Configuration

`app/core/config.py` (pydantic-settings, reads `.env` / `../.env`):

| Field | Default | Notes |
|---|---|---|
| `database_url` | `sqlite+aiosqlite:///./data/drops.db` | Compose sets `/data/drops.db` |
| `cors_origins` | `http://localhost:5173` | Comma-separated; allows credentials |
| `public_origin` | empty | Production origin for Origin checks |
| `allowed_hosts` | empty | Comma list for `TrustedHostMiddleware` |
| `registration_code` | empty | Invite code; empty = closed after the first user |
| `registration_open` | `false` | Explicit escape hatch for open signup |
| `owner_twitch_id` | empty | Bootstrap/claim the first admin |
| `session_ttl_days` | `30` | Absolute session lifetime |
| `session_cookie_secure` | `auto` | `auto`/`true`/`false` |
| `auth_rate_limit_per_minute` | `10` | Auth attempts per client IP per minute |
| `sunkwi_url` | `https://drops.sunkwi.com/api/twitch/drops` | Catalog endpoint |
| `drops_api_key` | empty | Optional; also controls cache TTL defaults |
| `twitch_client_id` / `secret` | empty | Helix app credentials (shared) |
| `twitch_gql_url` | `https://gql.twitch.tv/gql` | Internal GQL |
| `twitch_gql_client_id` | empty | Advanced override |
| `twitch_device_client_id` | empty → built-in first-party client | Progress login + GQL client id |
| `twitch_device_client_secret` | empty | Advanced |
| `twitch_oauth_redirect_uri` | `https://www.twitch.tv/` | Implicit grant redirect |
| `telegram_bot_token` | empty | One bot for all users |
| `telegram_chat_id` | empty | **Seed only** for the migrating owner |
| `poll_seconds` | 900 | Scan interval, min `min_poll_seconds` |
| `progress_poll_seconds` | 300 | Progress interval, min `min_progress_poll_seconds` |
| `watcher_poll_seconds` | 60 | Focus monitor/reconcile interval, min `min_watcher_poll_seconds` |
| `default_games` | `Rust,Minecraft` | New-user default whitelist |

`API_TOKEN` no longer exists. See [OPERATIONS.md](OPERATIONS.md) for the
deployment-facing list.

## Auth service

`AuthService` owns registration/login and account settings:

- `connect(redirect_url, invite_code, current_user)`:
  - parse + validate the implicit-grant token with Twitch and enforce the
    expected client id;
  - resolve the Twitch user id; load the active local user or apply the
    registration table (first user = admin; later users need a valid code or
    explicit open registration);
  - a different Twitch id while signed in raises a `409` conflict; inactive users
    get `403`;
  - seed default games only when `users.games_seeded` is false, then mark it
    true (`PUT /games` also marks it true);
  - store the token on `twitch_accounts`, fetch the profile (login fallback),
    create the session, set both cookies, and trigger the first progress sync
    **after** the session is committed. Never sync on a failed registration.
- `logout(raw_token)` deletes that session; `disconnect(user_id)` deletes the
  Twitch account and that user's personal progress/focus/completions but keeps
  the user and session.
- `update_telegram(user_id, chat_id, enabled)` updates only the current user.
  Disabling/clearing deletes pending `user_campaign_starts` rows so re-enabling
  does not send a backlog. Disabling an account also deletes its pending starts.
- `registration_state()` returns `{open, invite_required}` for `/auth/me`.
- Codes are compared with `secrets.compare_digest`; attempts are rate-limited per
  client IP (last `X-Forwarded-For` hop, or the single address nginx forwards;
  falls back to the peer address).

Sessions: 32 random bytes, base64url in `tdm_session`, SHA-256 hash stored. A
separate random CSRF token is stored hashed and echoed via `X-CSRF-Token`.
The middleware validates the token by cookie/header double-submit; it does not
compare against the stored hash.
Expiry is absolute (`session_ttl_days`); `last_used_at` is updated at most once
per hour. Expired rows are pruned at startup and in the scan job.

## Scan service (shared)

`ScanService.run()`:

1. `SunkwiProvider.fetch_games()` — 20s timeout; on 429/5xx/timeout returns the
   cache; `429` without cache raises `ProviderError`.
2. Upsert games. A user gets `DEFAULT_GAMES` once (`users.games_seeded=false`)
   on connect; clearing the selection persists and is not reseeded. There is no
   global selected flag.
3. Compute the union of selected games across active users.
4. Parse campaigns for that union; capture previous statuses, upsert campaigns +
   rewards, delete stale campaigns.
5. For each campaign transitioning to `ACTIVE`, create `user_campaign_starts`
   rows only for users tracking the game **and** Telegram-enabled with a chat id.
   Orphan pending rows are pruned.
6. Discover streams once via Helix for the union of games with a Twitch id.
7. Match streams to active campaigns using `allow`; replace shared
   `streams`/`stream_campaign_matches`.
8. Send each opted-in user their own start digest to their chat id. Claim
   `(user_id, campaign-started:{external_id})` atomically; on Telegram failure
   release the claim and keep the start row; on success delete that user's row.
9. Prune expired sessions.
10. Write a shared `ScanRun` (`ok`, error, counts).

New live streams are never sent to Telegram.

## Progress service (per user)

`ProgressService(session, user_id, settings, provider, telegram).run()`:

1. Load that user's `twitch_accounts`; no token → disconnected result.
2. If `reconnect_required`, skip without a provider call. There is **no
   refresh-token path** for the implicit grant.
3. `TwitchUserProvider.fetch_inventory()` → GQL `Inventory` persisted query; on
   `PersistedQueryNotFound`, retry with the raw query.
4. Flatten `dropCampaignsInProgress` with `parse_inventory`.
5. Read `earnedDropRewards` and persist `user_campaign_completions` for catalog
   campaigns whose claimed reward count reaches the catalog reward count; also
   mark a campaign completed when every in-progress drop is claimed.
6. Replace this user's `user_drop_progress`; commit.
7. Insert `user_progress_snapshots`; prune that user's rows >24h.
8. Notifications for this user:
   - ready drops (`is_ready` and not claimed) keyed `drop-ready:<drop_id>`
   - tightest deadline only, `campaign-ending:<gql_id>:2h` or `:24h`
   - claim `(user_id, key)` atomically before sending; one digest; release on
     failure.
9. On success set `last_synced_at`, clear `reconnect_required`/`last_error`. On a
   user-token 401/expiry set `reconnect_required` + redacted `last_error`. A
   global client misconfiguration must **not** set the per-user flag.

The worker loops active users with a Twitch account, one fresh session each, and
logs/continues on failure.

### Remaining-time / watch-rate math (`progress_metrics.py`)

- `remaining_minutes = max(0, required - current)` (claimed → 0).
- Rate uses snapshots from the last **2 hours**: oldest vs newest, requires at
  least 5 minutes span; `rate = delta_minutes * 60 / span_minutes`.
- Rate below `0.5` min/hour → `null` (not actually watching).
- Campaign remaining = **max** of the unclaimed drops' remaining minutes, not
  their sum. There is no ETA field.

## Watch queue

`GET /watch-queue` (`api/v1/watch_queue.py`,
`services/watch_queue_service.py`):

- Loads the **current user's** progress + snapshots.
- One flat SQL join for streams → matches → campaigns → games.
- Keeps only campaigns in that user's progress; dedupes by `external_id`.
- Sorts by earliest campaign end, then most remaining work, then viewers.
- Next drop = unclaimed drop with the smallest positive remaining minutes.
- `find_candidate()` is shared with the focused watcher.

## Streams

`GET /streams` (`api/v1/streams.py`, `repositories/streams.py`):

- One flat join for stream + game + campaign name/external id.
- Loads the current user's completions and omits completed campaigns.
- Drops streams with no remaining uncompleted campaign match.

## Focused watcher (per user)

`services/watch_focus_service.py` manages `user_watch_focus`, one row per user,
and is the only writer of focused mode:

- `GET /watcher` returns that user's state + up to 8 dispatchable candidates
  (current focus excluded).
- Enabling auto-selects their most urgent live candidate; disabling clears it.
  There is at most **one** watcher per user (`max_watchers: 1`).
- `POST /watcher/focus` supports `manual`, `auto` (optional campaign filter), and
  `next` (exclude the current stream).
- `reconcile()` runs per focus-enabled user every `WATCHER_POLL_SECONDS`. It
  resolves by `user_login` + `campaign_id` (stream rows are recreated each scan)
  and refreshes the snapshot. It does **not** auto-move.
- If the campaign is complete, it sends one completion notification to that
  user's chat and turns focus off. If the live went offline while the campaign
  still has time, it sends one offline notification per online session, keeps the
  target, and sets `status=offline`.
- Dedupe keys are scoped by `user_id` (`watch-offline:...`, `watch-complete:...`).
  Telegram failures release the claim for retry.
- Focus pointer only: no playback control, no watch heartbeats.

## Profile service

`ProfileService.refresh(user_id)` fetches `ViewerCard` and saves the profile on
`users`; `schedule(user_id)` runs one background refresh for a cold profile.
`/twitch/status` stays non-blocking. There is no singleton startup warm-up.

## Providers

### Sunkwi (`sunkwi.py`)

- Optional `X-API-Key`.
- In-memory cache; persists successful payloads to
  `<sqlite-dir>/sunkwi_cache.json` (atomic replace).
- Honors `X-RateLimit-Reset` / `Retry-After`; serves stale cache on
  429/5xx/timeouts/invalid payloads. Provider window: **1 request / 300s**.

### Twitch Helix (`twitch.py`)

- Client-credentials token, cached until near expiry (shared by all users).
- `GET /helix/streams` with pagination (up to 5 pages, 100 per page).
- 401 → refresh token and retry once.

### Twitch user (`twitch_user.py`)

- Implicit grant with a first-party public client; the user pastes the redirect.
- `parse_oauth_token` accepts a full URL with `#access_token=` or a raw token.
- `validate` uses `/oauth2/validate`.
- `fetch_inventory` uses GQL `Inventory` with a raw fallback;
  `fetchRewardCampaigns: true` adds `earnedDropRewards`.
- `fetch_profile` uses `ViewerCard`, saved on `users` via `ProfileService`.
- Sends Android client headers because GQL rejects third-party-app tokens.
- **Read-only**: no claim mutations, no watch heartbeats.

### Telegram (`telegram.py`)

- `send(message, chat_id)` targets a specific chat; `configured` means a bot
  token exists. No global chat fallback for regular sends.
- `TELEGRAM_CHAT_ID` only seeds the migrating owner.
- Provider errors and logs redact the bot token and never include the request
  URL; redacted text is safe for `last_error`.
- Notification policy: atomic per-user claim + one digest per run; no claim if
  unconfigured; failed send releases claims.

## Data access

- Personal repositories take `user_id`; all queries include it.
- `Campaign.raw` is `deferred=True` — written by scans, never read on API paths.
- `NotificationRepository.claim()` inserts inside a SAVEPOINT and catches
  `IntegrityError`; `release()` deletes a claim after a failed send.
- `ProgressRepository` replaces only that user's `user_drop_progress` rows each
  sync and manages that user's snapshots.
- Shared catalog/stream repositories stay user-agnostic.

## Tests

`backend/tests` covers:

- parsing/inventory, scan service (shared catalog, streams, per-user starts,
  retry), progress service (watch rate, digests, deadline windows, retry,
  reconnect semantics), notifications (claim/release/duplicate),
- watch queue and focused watcher (per-user isolation, manual/auto/next,
  offline, completion), completion ledger, streams/status APIs,
- auth (bootstrap, invite/closed/open registration, existing/inactive user,
  different-account conflict, cookie attributes, absolute expiry, CSRF,
  forwarded HTTPS, Origin/Host, rate limit),
- migration (legacy fixture, no-token bootstrap, empty `user_id`, expired token,
  conflicting user, partial failure/rerun, concurrent startup),
- admin (non-admin `403`, self-disable `400`, session revocation, no
  token/chat-id leakage),
- worker loops (one user fails, others continue; Telegram target/redaction).

Run:

```bash
cd backend
PYTHONPATH=$PWD pytest -q
ruff check app tests
```

The exact pass count is recorded in [STATUS.md](STATUS.md); after this change it
is higher than the old single-user baseline.

## Adding a backend feature

1. Add/modify models in `domain/models.py` with `user_id` and indexes for new
   personal query patterns.
2. Add Pydantic contracts in `domain/schemas.py` (additive where possible).
3. Put query logic in `repositories/`; orchestration in `services/`.
4. Add endpoint in `api/v1/` and register in `router.py`.
5. Add tests; update [API.md](API.md), [DATA_MODEL.md](DATA_MODEL.md),
   [BACKEND.md](BACKEND.md), [STATUS.md](STATUS.md), [CHANGELOG.md](CHANGELOG.md).
6. Use explicit loaders/flat joins for read paths; avoid `selectin` graphs for
   ID/name mappings.
7. Never return another user's rows; admin responses must stay safe-metadata
   only.

## Known limitations

- Single uvicorn worker; a heavy request can serialize others.
- SQLite writes are serialized; the worker is sequential per user.
- Twitch GQL is unofficial and can change without notice.
- Legacy implicit tokens have no refresh token; an expired token means reconnect.
- Manual `POST /scans` is synchronous (~2–3s) and admin-only.
- Per-user provider calls grow linearly with the number of active users.
