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
    rate_limit.py         in-process auth + per-user action limiters
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
    twitch_device_flows.py progress.py campaign_completions.py notifications.py
    campaign_starts.py watch_focus.py campaigns.py games.py streams.py scans.py
  services/
    auth_service.py       connect/complete_login/logout/disconnect/registration
    twitch_device_service.py  start/poll/cancel the Twitch device grant
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
   `checkfirst=True`, runs `run_schema_migrations()` (adds
   `twitch_accounts.client_id` and records `app_meta['twitch_device_login_v1']`),
   then runs `run_multi_user_migration()`.
3. Middleware:
   - `TrustedHostMiddleware` when `ALLOWED_HOSTS` is set.
   - CSRF check on unsafe `/api/v1/*` methods when a session cookie exists
     (public connect and device-start endpoints are exempt; device poll/cancel
     are not).
   - `Cache-Control: no-store` on authenticated API responses and every
     `/auth/twitch/device/*` response.
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
| `auth_global_rate_limit_per_minute` | `120` | Deployment-wide auth ceiling, checked after the per-IP bucket |
| `sunkwi_url` | `https://drops.sunkwi.com/api/twitch/drops` | Catalog endpoint |
| `drops_api_key` | empty | Optional; also controls cache TTL defaults |
| `twitch_client_id` / `secret` | empty | Helix app credentials (shared) |
| `twitch_gql_url` | `https://gql.twitch.tv/gql` | Internal GQL |
| `twitch_gql_client_id` | empty | Advanced override |
| `twitch_device_client_id` | empty → built-in Android client | Implicit login + legacy GQL fallback |
| `twitch_device_client_secret` | empty | Advanced |
| `twitch_device_grant_client_id` | built-in Smart TV client | Device-code grant client id (public) |
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

- `connect(redirect_url, invite_code, current_user)` is the advanced implicit
  fallback:
  - parse + validate the implicit-grant token with Twitch and enforce the
    **Android** client id (`twitch_device_client_id`);
  - delegate to `complete_login(...)` with that client id.

`complete_login(token, info, *, invite_code, current_user, client_id)` is shared
by both login flows and owns:

- resolve the Twitch user id; load the active local user or apply the
  registration gates. An empty `users` table is **not** open by itself: the
  first user is allowed only when the Twitch id matches non-empty
  `OWNER_TWITCH_ID`, a valid `REGISTRATION_CODE` is supplied, or
  `REGISTRATION_OPEN=true`. Later users need the code or explicit open
  registration. The first-admin role is claimed atomically
  (`claim_first_admin_slot`), so concurrent first logins yield one admin;
- a different Twitch id while signed in raises a `409` conflict; inactive users
  get `403`;
- seed default games only when `users.games_seeded` is false, then mark it
  true (`PUT /games` also marks it true);
- fetch the profile with the supplied client id, store the token and that client
  id on `twitch_accounts`, create the session, set both cookies, and trigger the
  first progress sync **after** the session is committed. Never sync on a failed
  registration.

`TwitchDeviceService` owns the device-code grant:

- `start(invite_code, current_user)` calls Twitch `/oauth2/device` with the Smart
  TV client id, stores the secret `device_code`, 8-character `user_code`,
  verification URI, invite/current-user binding, interval, and a 30-minute
  expiry. It returns only the opaque `flow_id` and display fields.
- `poll(flow_id)` atomically claims one upstream poll per row interval with a
  conditional `UPDATE` on `last_polled_at`; losers get `pending` without calling
  Twitch. It maps `authorization_pending`, `slow_down` (persisted +5s),
  `expired_token`, `access_denied`, and terminal invalid-device responses.
  Network/5xx/429 failures are transient and leave the flow pending. Success
  validates the token, enforces the flow's Smart TV client id, calls
  `complete_login`, and marks the flow `connected`; connected status is never
  downgraded.
- `cancel(flow_id)` deletes the row. Expired rows are deleted on start and during
  the worker scan.
- `logout(raw_token)` deletes that session; `disconnect(user_id)` deletes the
  Twitch account and that user's personal progress/focus/completions but keeps
  the user and session.
- `update_telegram(user_id, chat_id, enabled)` updates only the current user.
  Disabling/clearing deletes pending `user_campaign_starts` rows so re-enabling
  does not send a backlog. Disabling an account also deletes its pending starts.
- `registration_state()` returns `{open, invite_required}` for `/auth/me`. With
  no users, `open` is true only when an owner, code, or open registration is
  configured; `invite_required` is true only when the code is the gate.
- `set_user_active(user_id, False)` uses one conditional `UPDATE ... WHERE NOT
  EXISTS (another active admin)` and checks `rowcount`, so two concurrent
  demotions cannot leave the install without an admin.
- Codes are compared with `secrets.compare_digest`; attempts are rate-limited per
  client IP (last `X-Forwarded-For` hop, or the single address nginx forwards;
  falls back to the peer address) and then by a deployment-wide auth bucket.
  The per-IP check runs first, so one address cannot exhaust the global bucket
  before its own limit applies.
- Authenticated side-effect routes use small per-user in-process budgets
  (`progress.refresh` 2/min, `notifications.test` 3/min, `telegram.link` and
  `telegram.unlink` 3/min, `auth.me.update` 10/min) and return `429` with
  `Retry-After`.

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
10. Write a shared `ScanRun` (`ok`, error, counts). On failure store only
    `<ExceptionType>: scan failed` (never `str(exc)`); logs contain only the
    exception type. `ScanRunOut` and `/status` redact legacy raw rows too.

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
  `client_id` / `client_secret` / `grant_type` go in the POST **body**, never the
  query string.
- `GET /helix/streams` with pagination (up to 5 pages, 100 per page).
- 401 → refresh token and retry once.
- Provider errors contain only an operation label, the exception type, or an
  HTTP status; URLs, request bodies, tokens, and upstream response bodies are
  never included. `twitch_user.py` follows the same rule (GraphQL/transport
  error text and refresh response bodies are not surfaced).

### Twitch user (`twitch_user.py`)

- Implicit grant remains available as an advanced fallback; the primary login is
  the Smart TV device-code grant.
- `start_device_flow` calls `/oauth2/device` with
  `twitch_device_grant_client_id` and empty scopes.
- `poll_device_token` calls the token endpoint once with
  `urn:ietf:params:oauth:grant-type:device_code`; typed errors distinguish
  pending/slow-down/expired/denied/terminal from transient provider failures.
  Messages never include the device code, token, or upstream body.
- `parse_oauth_token` accepts a full URL with `#access_token=` or a raw token.
- `validate` uses `/oauth2/validate`.
- `fetch_inventory`/`fetch_profile` accept `client_id`; the `Client-Id` header is
  the account's issuing client (Smart TV for device logins, Android for
  implicit/legacy), falling back to `gql_client_id`.
- `fetch_inventory` uses GQL `Inventory` with a raw fallback;
  `fetchRewardCampaigns: true` adds `earnedDropRewards`.
- `fetch_profile` uses `ViewerCard`, saved on `users` via `ProfileService`.
- Sends Android user-agent/session headers because GQL rejects third-party-app
  tokens; only `Client-Id` varies per account.
- **Read-only**: no claim mutations, no watch heartbeats.

### Telegram (`telegram.py`)

- `send(message, chat_id)` targets a specific chat; `configured` means a bot
  token exists. No global chat fallback for regular sends.
- `TELEGRAM_CHAT_ID` only seeds the migrating owner.
- Provider errors and logs redact the bot token and never include the request
  URL; redacted text is safe for `last_error`.
- Notification policy: atomic per-user claim + one digest per run; no claim if
  unconfigured; failed send releases claims.
- The worker long-polls `getUpdates` when a bot token exists. The offset is
  persisted in `app_meta`; `/start <code>` links a private chat, `/start`
  re-enables an already linked chat (or points an unlinked chat at Settings →
  Connect Telegram), `/stop` disables alerts, and `/unlink` clears the link.
  Group chats are ignored. A chat id cannot be entered manually; only the link
  flow sets it.
- A link code may re-link the **same** chat, but it cannot replace a different
  non-empty `telegram_chat_id`; that returns `ok=false` and asks the user to
  unlink in Settings first. Chat lookup/enable/disable/unlink require
  `User.is_active`, so disabled accounts cannot drive bot commands. A partial
  unique index (`uq_users_telegram_chat_id`, non-empty values only) is the
  race-safe backstop; the link service catches `IntegrityError` and reports the
  chat as already linked.
- Replies are capped at 10 per chat per minute. Repeated invalid or spam
  commands are still consumed and the offset advances, but suppressed replies
  stop one chat from generating unbounded outbound messages.
- The whole poll iteration (including offset load/save) is guarded: database or
  provider failures log only the exception type and back off exponentially from
  5s to a 300s cap. A done-callback logs unexpected poller termination.

## Data access

- Personal repositories take `user_id`; all queries include it.
- `Campaign.raw` is `deferred=True` — written by scans, never read on API paths.
- `NotificationRepository.claim()` inserts inside a SAVEPOINT and catches
  `IntegrityError`; `release()` deletes a claim after a failed send.
- `ProgressRepository` replaces only that user's `user_drop_progress` rows each
  sync and manages that user's snapshots.
- `users.telegram_chat_id` has a partial unique index for non-empty values.
  `init_db()` creates missing model indexes individually and logs/skips one that
  cannot be created (e.g. legacy duplicate chat ids) instead of blocking startup;
  the link service still enforces uniqueness with a trimmed lookup.
- Shared catalog/stream repositories stay user-agnostic.

## Tests

`backend/tests` covers:

- parsing/inventory, scan service (shared catalog, streams, per-user starts,
  retry), progress service (watch rate, digests, deadline windows, retry,
  reconnect semantics), notifications (claim/release/duplicate),
- watch queue and focused watcher (per-user isolation, manual/auto/next,
  offline, completion), completion ledger, streams/status APIs,
- auth (bootstrap gates: owner match/mismatch, invite code, open, closed,
  concurrent first users; existing/inactive user, different-account conflict,
  cookie attributes, absolute expiry, CSRF, forwarded HTTPS, Origin/Host,
  per-IP + global auth rate limit, per-user action limits, atomic last-admin
  disable),
- device login (start shape, TTL clamp, pending/slow-down/duplicate throttle,
  concurrent atomic poll claim, transient upstream stay-pending, success/session
  cookies, first-sync scheduling, denied/expired/cancel/one-time/cleanup,
  no-downgrade of a connected flow, live-session CSRF cancel, no-store),
- per-account client ids (implicit Android, device Smart TV, legacy fallback,
  GQL/profile/inventory header selection),
- games selection bounds (50 entries / 100-char names, repository guard),
- provider redaction (Twitch client secret never in errors, scan rows, or
  `/status`; device grant errors never include codes/tokens/bodies),
- migration (legacy fixture, no-token bootstrap, empty `user_id`, expired token,
  conflicting user, partial failure/rerun, concurrent startup; additive
  `client_id` column preserves rows and reruns as a no-op),
- admin (non-admin `403`, self-disable `400`, session revocation, no
  token/chat-id leakage),
- worker loops (one user fails, others continue; Telegram target/redaction;
  per-chat reply cooldown).

Run:

```bash
cd backend
PYTHONPATH=$PWD pytest -q
ruff check app tests
```

The exact pass count is recorded in [STATUS.md](STATUS.md); the current floor is
**307 tests**.

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
- The auth/action limiters are in-process (per worker). Running multiple
  workers would multiply the effective budgets; the deployment assumes one.
- SQLite writes are serialized; the worker is sequential per user.
- Twitch GQL is unofficial and can change without notice.
- Device-code login does not eliminate device-grant phishing: a user who enters
  an attacker-supplied code can authorize the attacker's flow. The UI must warn
  to enter only self-generated codes; see ADR-021.
- The Smart TV device client is public and unofficial; verify the first live
  device-flow inventory sync after deploy.
- Legacy implicit tokens have no refresh token; an expired token means reconnect.
- Manual `POST /scans` is synchronous (~2–3s) and admin-only.
- Per-user provider calls grow linearly with the number of active users.
