# API reference

Base path: `/api/v1` (through nginx at `/api/v1` on port 8282, or directly on
port 8000). Interactive OpenAPI: `http://<host>:8000/docs`.

## Authentication and sessions

Twitch is the only identity provider; there are no passwords or local tokens.
`API_TOKEN` / `X-API-Token` is retired.

Public endpoints: `GET /health`, `GET /auth/me`,
`GET /auth/twitch/authorize`, `POST /auth/twitch/connect`. Every other endpoint
requires an active session. Admin-only: `POST /scans`, `GET /admin/users`,
`PATCH /admin/users/{id}`.

`GET /auth/me` is the exception to `401`: when reachable it always returns `200`,
with `authenticated: false` and `user: null` when there is no valid session. It
never redirects or `401`s; the SPA uses it to decide whether to show the gate.

Sign-in:

1. The SPA calls `GET /auth/me`; without a session it shows the sign-in screen.
2. `GET /auth/twitch/authorize` returns the implicit-grant authorize URL and
   redirect URI.
3. The user authorizes on Twitch and pastes the full
   `https://www.twitch.tv/#access_token=...` URL, plus the invite code for a new
   account.
4. `POST /auth/twitch/connect` validates the token with Twitch, resolves the
   Twitch user id, creates or loads the local user, and sets both cookies.
5. The SPA refreshes `/auth/me`; all personal queries then load for that user.

### Cookies and CSRF

- `tdm_session` — opaque session token, `HttpOnly`, `SameSite=Lax`, `Path=/`.
  Only its SHA-256 hash is stored server-side.
- `tdm_csrf` — readable random token. Send it as `X-CSRF-Token` on every
  `POST`/`PUT`/`PATCH`/`DELETE`. The backend uses cookie/header double-submit:
  it compares the `tdm_csrf` cookie with the header using
  `secrets.compare_digest`. The session row stores a hash of the token for
  future use but the middleware does **not** compare against that stored hash.
  The public connect endpoint is exempt.
- Both cookies are `Secure` according to `SESSION_COOKIE_SECURE`: `auto` uses
  the effective scheme from `X-Forwarded-Proto`, `true`/`false` forces it.
- Sessions expire after an **absolute** `SESSION_TTL_DAYS` (30 by default). They
  do not slide; expired sessions return `401`.
- Unsafe requests with an `Origin` header must match `PUBLIC_ORIGIN` (or a
  configured `CORS_ORIGINS` entry, or the request's own origin when neither is
  set). `ALLOWED_HOSTS`, when set, rejects unexpected `Host` headers.
- Authenticated API responses send `Cache-Control: no-store`.
- Signing out deletes the session. A disabled user's sessions are deleted and
  their requests return `401`.

### Registration rules

| State | New user can register? | Invite code field? |
|---|---|---|
| No users yet | Yes — first user becomes `admin`, code ignored | No |
| Users exist, `REGISTRATION_CODE` set | Yes | Yes |
| Users exist, code empty, `REGISTRATION_OPEN=true` | Yes | No |
| Users exist, code empty, `REGISTRATION_OPEN=false` | No — `403` | No ("registration closed") |

`GET /auth/me` exposes `registration.open` and `registration.invite_required`
using this table. Connecting a different Twitch id while signed in returns
`409`; sign out first. The local user is permanently bound to one Twitch id.

## Conventions

- JSON in/out; `Content-Type: application/json` for bodies.
- Timestamps are ISO-8601 strings/datetimes; Twitch campaign end dates keep the
  provider's string form (often with `Z`).
- Errors use FastAPI's `{"detail": "..."}`. Common codes:
  - `400` not configured / invalid token / bad input
  - `401` missing, invalid, or expired session
  - `403` registration closed, bad invite code, bad CSRF token, inactive user,
    or not an admin
  - `404` not found / no scans yet
  - `409` Twitch account conflict (different Twitch id while signed in)
  - `429` auth rate limit (`AUTH_RATE_LIMIT_PER_MINUTE`, default 10/min/IP)
  - `502` upstream provider failure
- Personal endpoints are scoped to the session's user. Admin endpoints never
  return tokens or Telegram chat ids.

## Endpoint summary

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | public | Liveness + configured providers |
| GET | `/auth/me` | public | Session user + registration state |
| GET | `/auth/twitch/authorize` | public | Implicit-login authorize URL |
| POST | `/auth/twitch/connect` | public | Accept pasted redirect URL/token; sets cookies |
| POST | `/auth/logout` | session | Delete the current session |
| PATCH | `/auth/me` | session | Update current user's Telegram settings |
| POST | `/auth/twitch/disconnect` | session | Clear current user's Twitch data |
| GET | `/status` | session | Dashboard summary for the current user |
| GET | `/games` | session | Catalog games with per-user `selected` |
| PUT | `/games` | session | Replace current user's selected games |
| GET | `/campaigns` | session | Campaigns for the current user's games |
| GET | `/streams` | session | Live streams for the current user |
| POST | `/scans` | admin | Run a global catalog/stream scan |
| GET | `/scans/latest` | session | Latest shared scan run |
| POST | `/notifications/test` | session | Send to the current user's chat |
| GET | `/progress` | session | Current user's drop progress |
| POST | `/progress/refresh` | session | Sync current user's Twitch inventory |
| GET | `/watch-queue` | session | Current user's live queue |
| GET | `/watcher` | session | Current user's focus state + candidates |
| PATCH | `/watcher` | session | Enable/disable current user's focused mode |
| POST | `/watcher/focus` | session | Focus/auto-pick/next for current user |
| DELETE | `/watcher` | session | Stop the current user's focused watcher |
| GET | `/twitch/status` | session | Current user's Twitch connection/profile |
| GET | `/admin/users` | admin | Safe user list |
| PATCH | `/admin/users/{id}` | admin | Enable/disable a user |

---

## Health

`GET /health`

```json
{
  "ok": true,
  "database": true,
  "twitch_api_configured": true,
  "telegram_configured": true,
  "drops_api_configured": true,
  "drops_api_keyed": true
}
```

## Auth

`GET /auth/me` (public)

```json
{
  "authenticated": true,
  "user": {
    "id": 1,
    "login": "shalevs343",
    "display_name": "shalevs343",
    "profile_image_url": "https://static-cdn.jtvnw.net/...",
    "role": "admin",
    "telegram_enabled": true,
    "telegram_chat_id": "123456789"
  },
  "registration": { "open": false, "invite_required": true },
  "telegram_bot_configured": true
}
```

Unauthenticated: `authenticated: false`, `user: null`; registration state is
still returned so the sign-in screen knows whether to show an invite field.

`GET /auth/twitch/authorize` (public)

```json
{
  "authorize_url": "https://id.twitch.tv/oauth2/authorize?client_id=...&redirect_uri=...&response_type=token",
  "redirect_uri": "https://www.twitch.tv/"
}
```

`POST /auth/twitch/connect` (public)

```json
{ "redirect_url": "https://www.twitch.tv/#access_token=...&scope=&state=...", "invite_code": "<code>" }
```

- Accepts a full redirect URL or a raw token (`400` if missing/invalid).
- Enforces the expected Twitch client id and validates the token with Twitch.
- Existing active user: logs in; the invite code is ignored.
- New user allowed by the registration table: creates the local user, seeds
  default games, makes the first user `admin`, stores the token, fetches the
  profile, and starts the first progress sync after the session is committed.
- Sets `tdm_session` and `tdm_csrf` on success; refresh `/auth/me` for the user.
- `403` closed registration / wrong code / inactive user, `409` different Twitch
  id while signed in, `429` rate limit.

`PATCH /auth/me` (session)

```json
{ "telegram_chat_id": "123456789", "telegram_enabled": true }
```

Updates only the current user. Disabling `telegram_enabled` (or clearing the chat
id) deletes that user's pending campaign-start rows, so re-enabling later does
not send a backlog. A non-empty chat id already owned by another account is
rejected with `409`.

`POST /auth/logout` (session) — deletes the current session and clears both
cookies. Other users' sessions are untouched.

`POST /auth/twitch/disconnect` (session) — clears the current user's stored
Twitch account/token and personal progress, snapshots, completions,
notifications, focus, and pending starts. The local user, profile fields, and
session remain. The UI then shows "reconnect Twitch".

## Admin

`GET /admin/users` (admin) → safe user list:

| Field | Notes |
|---|---|
| `id`, `login`, `display_name`, `role` | local account |
| `is_active` | disabled users cannot log in or sync |
| `created_at`, `last_login_at` | timestamps |
| `telegram_enabled` | opt-in flag only |

Never returns tokens, chat ids, progress, or session data.

`PATCH /admin/users/{id}` (admin)

```json
{ "is_active": false }
```

- `{is_active}` is the only accepted change.
- Disabling deletes that user's sessions, disables their focus, and skips them
  in worker loops; it does not delete their rows or data.
- Admins cannot disable themselves (`400`); non-admins get `403`.

## Status

`GET /status` (session)

```json
{
  "app": "Twitch Drops Manager",
  "user": { "id": 1, "login": "shalevs343", "role": "admin" },
  "twitch_configured": true,
  "telegram_configured": true,
  "telegram_ready": true,
  "games_selected": ["War Thunder"],
  "campaign_count": 1,
  "stream_count": 5,
  "last_scan": {
    "id": 12,
    "started_at": "2026-11-06T19:51:53",
    "finished_at": "2026-11-06T19:51:56",
    "ok": true,
    "error": null,
    "campaign_count": 118,
    "stream_count": 5
  },
  "last_error": null,
  "twitch_user_connected": true,
  "twitch_login": "shalevs343",
  "poll_seconds": 900,
  "min_poll_seconds": 300,
  "progress_poll_seconds": 300,
  "min_progress_poll_seconds": 60,
  "watcher_poll_seconds": 60,
  "min_watcher_poll_seconds": 30,
  "drops_api_keyed": true
}
```

`games_selected`, `campaign_count`, and `stream_count` are per current user
(selected games and their catalog/live counts). `last_scan` is the shared scan
run and its `campaign_count`/`stream_count` cover the union of all users'
tracked games; `last_error` is shared scan state. `telegram_ready` means the bot
token exists **and** this user has opted in with a chat id. Twitch connection
details are per user in `/twitch/status`.

## Games

`GET /games` (session) → `GameOut[]`. `selected` reflects the current user;
the catalog itself is shared.

```json
[{
  "id": 1,
  "name": "War Thunder",
  "box_art_url": "https://...",
  "twitch_game_id": "66366",
  "selected": true,
  "campaign_count": 1
}]
```

`PUT /games` (session)

```json
{ "games": ["War Thunder", "Rust"] }
```

Response: `{ "games": ["War Thunder", "Rust"] }` (names actually selected for
the current user). Replaces only that user's selection. Names are matched
case-insensitively and de-duplicated. A name that does not yet exist in the
catalog is created as a tracked `Game` row with no Twitch metadata; a later scan
fills in the game id and box art. Default games are seeded once on the account's
first connect; clearing every game is persisted, so a later login does not
restore the defaults.

## Campaigns

`GET /campaigns?game=War%20Thunder&status=ACTIVE&active_only=false` (session)

- `game` — exact game name (case-insensitive); omit for the current user's games.
- `status` — exact status (upper-cased), e.g. `ACTIVE`.
- `active_only` — only `ACTIVE`.

Returns the shared catalog filtered to the current user's selected games.
`completed` is per user: `true` when that account claimed every reward in the
campaign. Completion is persisted in `user_campaign_completions`, so it stays
true after Twitch removes the campaign from `dropCampaignsInProgress`.

When a tracked game's campaign becomes `ACTIVE`, the scan records a pending
start for each user tracking that game who has Telegram enabled with a chat id.
Users who opted out get no pending backlog.

## Streams

`GET /streams?game=War%20Thunder&live=true` (session)

- `live` defaults to `true`; pass `false` for offline rows (if any).
- Returns `StreamOut[]` for the current user, including `matching_campaigns`.
- Only streams that still advance at least one of that user's **uncompleted**
  campaigns are returned. Completed campaigns are omitted; a stream whose only
  matches are completed is dropped.

## Scans

`POST /scans` (admin) — runs the shared catalog/stream scan synchronously
(~2–3s). Non-admins get `403`.

```json
{ "ok": true, "campaign_count": 118, "stream_count": 5, "notified_count": 2 }
```

Errors: `400` provider not configured, `502` upstream failure. The scan is also
recorded in the shared `scan_runs`. The scan computes the union of selected games
across active users and discovers live streams once for everyone.
`notified_count` sums successfully delivered campaign-start events across
opted-in users. New live streams are **not** sent to Telegram.

`GET /scans/latest` (session) → `ScanRunOut`; `404` if no scan has run.

## Notifications

`POST /notifications/test` (session)

- `400` if the bot token is missing or the current user has no chat id/opt-in;
  otherwise sends to **that user's** chat.
- Response: `{ "sent": true }`.

Provider errors are redacted; the bot token and Telegram request URL never reach
logs or `last_error`.

## Telegram auto-link

`POST /telegram/link` (session) → one-time deep link:

```json
{
  "deep_link": "https://t.me/<bot>?start=<code>",
  "expires_at": "2026-11-12T17:00:00Z",
  "bot_username": "<bot>"
}
```

- `400` if the bot token is missing, `502` if Telegram cannot report the bot
  username, `429` when the per-user link rate limit is hit.
- Only a SHA-256 hash of the code is stored; codes expire after 10 minutes and
  are consumed on first successful use.
- Opening the link and pressing Start in the bot's private chat links that chat
  to the current user and enables alerts. Group chats are ignored.

`POST /telegram/unlink` (session) → `{ "unlinked": true }`; clears that user's
chat id, disables alerts, and deletes pending starts and link codes. `404` if
the user row no longer exists.

## Progress

`GET /progress` (session) → `ProgressCampaignOut[]` for the current user. Shape
is unchanged from the single-user contract:

```json
[{
  "campaign_id": "3df8df9c-...",
  "campaign_name": "WTCS Pro Grand Finals",
  "game_name": "War Thunder",
  "game_box_art_url": "https://...",
  "campaign_ends_at": "2026-11-12T09:59:59.999Z",
  "claimed_count": 0,
  "total_count": 7,
  "remaining_minutes": 1260,
  "drops": [{
    "drop_id": "2abc74f1-...",
    "drop_name": "50% Silver Lion Booster",
    "required_minutes": 30,
    "current_minutes": 30,
    "percent": 100,
    "is_claimed": false,
    "is_ready": true,
    "starts_at": "2026-11-05T10:01:57Z",
    "ends_at": "2026-11-12T09:59:59.999Z",
    "benefits": ["50% SL Booster"],
    "remaining_minutes": 0,
    "rate_minutes_per_hour": 12.0
  }]
}]
```

Campaign `remaining_minutes` is the **largest** remaining requirement among the
campaign's unclaimed drops, not the sum. Completed campaigns that left Twitch's
in-progress inventory are appended from the user's completion ledger + catalog
rewards (all drops claimed, sorted last).

`POST /progress/refresh` (session) — syncs only the current user.

```json
{ "connected": true, "campaign_count": 1, "drop_count": 7, "notified_count": 0 }
```

Returns `200` with `connected: false` when the current user has no Twitch
connection or is already flagged `reconnect_required`. Errors: `400` when the
call itself detects a missing/expired token or the global client is not
configured, `502` GQL/provider failure. One user's failure does not affect other
users' syncs. Clients should show a reconnect warning for `connected: false`,
not a success message.

## Watch queue

`GET /watch-queue` (session) → `WatchQueueItemOut[]` for the current user,
ordered by urgency. Returns `[]` when the user has no Twitch connection or no
campaign is in progress. Campaign `remaining_minutes` uses the same
max-of-open-drops rule as `/progress`. Item shape is unchanged.

## Focused watcher

Each user has at most one focused watcher (`max_watchers: 1`), persisted per
user. It is a **queue focus pointer**: it never plays a stream, sends watch
heartbeats, or simulates viewing.

`GET /watcher` (session) → `WatchStateOut` for the current user, including
`enabled`, `status`, `reason`, `focus`, and up to 8 `candidates` (the current
focus is excluded). Shape is unchanged.

`status` is `idle`, `focused`, `offline`, or `waiting`. `auto_move` is always
`false`.

`PATCH /watcher` (session) `{"enabled": true}` — enabling auto-selects this user's
most urgent live candidate; disabling clears their focus.

`POST /watcher/focus` (session)

```json
{ "stream_id": 2, "campaign_id": "3df8df9c-...", "strategy": "manual" }
```

- `manual` — both ids required; must be in this user's queue.
- `auto` — most urgent candidate; optional `campaign_id` narrows it.
- `next` — another live than the current focus; keeps the target with
  `reason: "next-unavailable"` when none exists.
- Invalid/expired targets return `400`.

`DELETE /watcher` (session) disables focus and clears the target. The worker
reconciles each enabled user every `WATCHER_POLL_SECONDS`, sends only to that
user's chat, and does not auto-move.

## Twitch connection

`GET /twitch/status` (session) → the current user's connection.

```json
{
  "connected": true,
  "login": "shalevs343",
  "user_id": "252776906",
  "expires_at": null,
  "display_name": "shalevs343",
  "profile_image_url": "https://static-cdn.jtvnw.net/...",
  "connected_at": "2026-11-06T18:58:44",
  "reconnect_required": false,
  "last_error": null,
  "last_synced_at": "2026-11-12T09:00:00"
}
```

- `reconnect_required` is set when Twitch rejects **this user's** token (401 or
  expiry). The worker skips that user until a successful reconnect/sync clears
  it. Global client misconfiguration never sets the per-user flag.
- When the user's profile is empty, the response is immediate and one background
  refresh is scheduled for that user; the next poll returns the stored profile.
- There is no refresh-token path for the legacy implicit grant: reconnect Twitch.

## Caching / rate-limit behavior

- Catalog: persisted cache + in-memory; 1 request/300s provider window; stale
  data is served during 429/5xx/timeouts.
- Progress: no HTTP cache; the worker refreshes each user every 300s; the UI
  polls.
- Profile: persisted on `users`; in-memory GQL cache is only used for the initial
  fetch.
- Auth: `AUTH_RATE_LIMIT_PER_MINUTE` (default 10) attempts per client IP per
  minute; exceeding it returns `429`. nginx forwards one resolved client address
  (see [OPERATIONS.md](OPERATIONS.md)); if the TLS proxy cannot supply the client
  IP, public requests can share one bucket.
- Authenticated responses: `Cache-Control: no-store`.
- nginx gzips JSON/JS/CSS and caches hashed assets immutably.

## Breaking-change policy

This change is intentionally breaking for API clients: `API_TOKEN` is gone,
`/twitch/connect` and `/twitch/logout` are replaced by the `/auth/*` endpoints,
and cookies are required. See [CHANGELOG.md](CHANGELOG.md). Prefer additive
fields after this. If a field must change, update `frontend/src/api/types.ts`,
[FRONTEND.md](FRONTEND.md), this file, and the changelog in the same change.
