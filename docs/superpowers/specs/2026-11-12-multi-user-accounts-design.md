# Multi-user Accounts — Twitch Login + Per-user Data

**Date:** 2026-11-12
**Status:** Draft for approval
**Supersedes:** ADR-009 (no local user accounts)

## Intent

The app is currently hard-wired to one Twitch account. Make it usable by a small
group of friends now, with room to grow later: each person connects their own
Twitch account, the server keeps a local user row tied to that Twitch identity,
and every personal view and background job is scoped to that user.

Twitch remains the only identity provider. There are no passwords or email
accounts. A shared invite code gates first-time registration so the public URL
does not become open signup.

## Goals

- Twitch-only sign-in that feels like the current "Connect Twitch" flow.
- A local `users` table keyed by Twitch user id, plus server-side sessions.
- No token-refresh machinery: the implicit grant has no refresh token, so an
  expired/invalid token means "reconnect Twitch".
- Per-user Twitch token, profile, selected games, drop progress, completed
  campaigns, watch focus, and notification ledger.
- Shared catalog and live-stream data: scans run once for everyone.
- Per-user, opt-in Telegram notifications to each user's own chat id.
- First user is admin; admins can disable users. Registration code can be rotated.
- Existing owner data is migrated to the owner's account on upgrade.
- The design remains portable to Postgres and a job queue if the group grows
  beyond what one SQLite writer and the Pi can handle.

## Non-goals

- Passwords, email verification, password reset, or local-account recovery.
- Open registration by default. A setting can open it later.
- Letting one user see another user's progress, games, or watch focus.
- Per-user Twitch client credentials. The app keeps one first-party Twitch client
  for the read-only GQL inventory.
- Encrypting OAuth tokens at rest. Tokens stay plaintext in SQLite for now, same
  as today; protecting the volume/host remains the security boundary.
- Claiming rewards or automating watching (ADR-002 still applies).
- Horizontal scaling, Postgres, Redis, or a separate job runner in this phase.

## Approaches considered

### A. Twitch-as-login + server session cookie — **chosen**

The existing implicit-grant flow stays. The backend validates the pasted token
with Twitch, maps it to a local user by Twitch user id, stores the token, and
issues an opaque session cookie. All personal endpoints resolve the current user
from that cookie.

Why it wins: one identity source, no password surface, the smallest change to a
flow users already know, and it works for any number of people without a second
account system.

### B. Local accounts, then link Twitch — rejected

Username/email + password registration, followed by a separate Twitch link step.
Familiar, but adds password storage, reset flows, and a second security surface
for no product gain when Twitch already proves identity.

### C. Browser-stored Twitch token — rejected

Keep the token in `localStorage` and send it with every request. Avoids a users
table, but exposes the token to XSS, makes per-user background jobs awkward, and
still needs server-side token storage for the worker.

## Product decisions

| Decision | Call | Reason |
|---|---|---|
| Registration | Shared `REGISTRATION_CODE` from env; first user bootstraps without it; a missing code means **closed**, never open | Small friend group now; rotate/clear the code to close the door |
| Roles | First user is `admin`; others are `user` | Enough to manage access without an admin product |
| Admin powers | List users, enable/disable, trigger global scans | Keeps shared provider work controlled |
| Shared data | `games`, `campaigns`, `rewards`, `streams`, matches, scan runs | Twitch catalog/streams are public, not personal |
| Personal data | token/profile, selected games, progress, snapshots, completions, focus, notifications | These differ per account |
| Telegram | One bot token in env; each user stores an optional numeric chat id and opt-in flag | No per-user bot registration; owner can keep the existing chat |
| Switching Twitch accounts | Sign out first; connecting a different Twitch id while signed in returns `409` | Prevents silently moving data to another account |
| Legacy data | Assigned to the existing token's Twitch account during migration | Owner keeps progress after one re-login |

### Registration rules

Two environment settings control new accounts:

- `REGISTRATION_CODE` — shared invite code; empty by default.
- `REGISTRATION_OPEN` — boolean, default `false`; explicit escape hatch for an
  intentionally open deployment.

| State | New user can register? | Invite code field? |
|---|---|---|
| No users yet | Yes — first user becomes admin, code ignored | No |
| Users exist, `REGISTRATION_CODE` set | Yes | Yes |
| Users exist, code empty, `REGISTRATION_OPEN=true` | Yes | No |
| Users exist, code empty, `REGISTRATION_OPEN=false` | No — `403` | No; show "registration closed" |

`GET /auth/me` exposes `registration_open` and `invite_required` using this table
so the SPA never shows a field that cannot work and never silently opens signup
when the code is missing.

## Architecture

### Authentication flow

1. An unauthenticated visitor opens the app. The SPA calls `GET /auth/me` and
   renders the sign-in screen when there is no active session.
2. `GET /auth/twitch/authorize` returns the existing implicit-grant URL and
   redirect URI. It is public because no session exists yet.
3. The user authorizes on Twitch and pastes the full
   `https://www.twitch.tv/#access_token=...` URL, plus the invite code if this is
   a new account.
4. `POST /auth/twitch/connect` parses and validates the token (`/oauth2/validate`),
   enforces the expected Twitch client id, and resolves the Twitch user id.
   - Existing active user: log in. Invite code is ignored.
   - New Twitch user allowed by the registration table: create the local user +
     Twitch account, seed default games, make the first user admin.
   - New Twitch user not allowed (closed, or wrong code): `403`.
   - Inactive user: `403` and no session.
   - Signed-in user connecting a different Twitch id: `409`; sign out first.
5. The backend fetches the Twitch profile, stores it on the user, creates a
   session row, sets the cookie, and triggers the first progress sync for that
   user.
6. `POST /auth/logout` deletes the session and clears the cookie.
7. `POST /auth/twitch/disconnect` clears that user's token, profile, progress,
   snapshots, completions, and focus, but keeps the local account and session.

### Sessions and CSRF

- Opaque random 32-byte session token, base64url in an `HttpOnly` `tdm_session`
  cookie. Only its SHA-256 hash is stored in `user_sessions`.
- A separate random CSRF token is set in a readable `tdm_csrf` cookie and must be
  echoed in `X-CSRF-Token` on every unsafe method. The backend compares the two
  with `secrets.compare_digest`. This protects cookie-authenticated requests even
  when a browser omits `Origin`.
- Cookie attributes on both cookies: `SameSite=Lax`, `Path=/`, and `Secure`
  controlled by `SESSION_COOKIE_SECURE`:
  - `auto` (default): Secure when the effective request scheme is HTTPS.
  - `true`/`false`: explicit override.
- The effective scheme comes from `X-Forwarded-Proto`. Today nginx overwrites it
  with `$scheme` (`http` behind Tailscale Funnel), so the proxy config changes to
  preserve the inbound value and fall back to `$scheme` when absent.
- **Absolute** 30-day expiry (`SESSION_TTL_DAYS`, default 30). Sessions do not
  slide; the cookie `Max-Age` and the database row expire together. Users sign in
  again after 30 days.
- `last_used_at` is updated at most once per hour for observability.
- Expired sessions are pruned at startup and during the worker scan.
- Origin defense-in-depth: unsafe methods with an `Origin` header must match
  `PUBLIC_ORIGIN` when it is set, otherwise a configured `CORS_ORIGINS` entry;
  if neither is set, the Origin must match the request's `scheme://host[:port]`.
  A request without `Origin` still needs the CSRF token.
- Add `TrustedHostMiddleware` when `ALLOWED_HOSTS` is set, so a spoofed `Host`
  cannot influence same-origin fallback checks.
- CORSMiddleware gets `allow_credentials=True` for the local Vite dev origin.
  Same-origin production traffic does not need CORS.
- The shared `API_TOKEN` / `X-API-Token` mechanism is retired. Sessions and roles
  replace it. `/health` stays public for Uptime Kuma.
- Authenticated API responses send `Cache-Control: no-store`.

### Data model

New tables are added; the old single-user tables are left untouched for rollback
and copied into the new ones once. This follows the existing `create_all` +
side-table pattern because SQLite cannot safely add the required uniqueness
constraints in place.

| Table | Purpose | Key constraints |
|---|---|---|
| `users` | Local account, Twitch identity, and profile | `twitch_user_id` non-empty unique; `login`, `display_name`, `profile_image_url`, `role`, `is_active`, Telegram fields |
| `user_sessions` | Server-side sessions | `token_hash` unique; indexed `user_id`, `expires_at`; stores CSRF token hash |
| `twitch_accounts` | Per-user OAuth tokens and sync health | `user_id` unique; `access_token`, `expires_at`, `connected_at`, `last_synced_at`, `last_error`, `reconnect_required` |
| `user_games` | Per-user selected games | unique `(user_id, game_id)` |
| `user_drop_progress` | Latest inventory per user | unique `(user_id, drop_id)` |
| `user_progress_snapshots` | Watch-rate history per user | index `(user_id, drop_id, recorded_at)` |
| `user_campaign_completions` | Claimed campaign ledger per user | unique `(user_id, campaign_gql_id)` |
| `user_watch_focus` | One focus pointer per user | `user_id` unique; no singleton id check |
| `user_notifications` | Per-user dedupe ledger | unique `(user_id, dedupe_key)` |
| `user_campaign_starts` | Per-user pending start events | unique `(user_id, external_id)` |
| `app_meta` | Migration/version flags | `key` primary key |

Ownership rules:

- `users.twitch_user_id` is the single authoritative Twitch identity. It is
  required (non-empty) and unique; `twitch_accounts` does not duplicate it.
- `users` owns `login`, `display_name`, `profile_image_url`, `role`,
  `is_active`, `telegram_chat_id` (empty = not set), and `telegram_enabled`
  (opt-in). No separate settings table is needed yet.
- `twitch_accounts` owns only the token, expiry, connected timestamp, and sync
  health. Reconnect updates the token row and the user's profile fields in one
  transaction.
- Disconnect deletes the `twitch_accounts` row and that user's personal progress
  tables, but keeps the `users` row and profile.

A local user is permanently bound to one Twitch user id. Signing out and
connecting a different Twitch account creates or logs into a separate local
user; it does not relink the old one. This is intentional and documented in the
UI.

Global tables keep their current schema. `games.selected` becomes legacy and is
ignored by the API; selected games live in `user_games`. If a game is tracked by
name before it exists in the catalog, the existing "create a Game row" behavior
is kept and the row is linked through `user_games`.

Completion, progress, notification, and start rows cascade on user deletion, but
the API only disables users rather than deleting them.

### Worker changes

The scheduler intervals stay the same. Each job isolates failures per user so one
bad token does not stop everyone.

- **Scan (once):**
  1. Fetch and upsert the shared catalog.
  2. Compute the union of selected games across active users.
  3. Discover live streams once for that union and replace shared stream rows.
  4. For each campaign transitioning to `ACTIVE`, create `user_campaign_starts`
     rows only for users tracking that game **and** opted into Telegram with a
     chat id. Users who opt out have no pending backlog.
  5. Send each opted-in user their own start digest to their own chat id, claiming
     `user_notifications` first and deleting that user's start row on success.
- **Progress (loop over users with a Twitch account):**
  1. Open a separate session per user.
  2. Skip users already marked `reconnect_required`; otherwise fetch inventory
     with the stored token and replace only that user's `user_drop_progress` rows
     and snapshots.
  3. Update that user's completions and send ready/deadline digests to that
     user's chat id.
  4. On success, record `last_synced_at`, clear `reconnect_required`, and clear
     `last_error`. On a user-token `401`/expiry, set `reconnect_required` and
     `last_error` instead of retrying forever. Global client misconfiguration
     must not set the per-user flag.
  5. Log and continue on failure.
- **Watcher (loop over users with focus enabled):** reconcile each user's focus
  against their own queue and notify only that user. Progress and focus queries
  take `user_id`.
- **Session cleanup:** delete expired sessions once per scan run or at startup.
- **Profile warm-up:** remove the singleton startup path. Fetch the profile on
  connect; if `/twitch/status` finds a user with an empty profile, schedule one
  background refresh for that user id only.

Manual API actions operate on the current user. Global scans are admin-only.
The worker remains sequential; with dozens of users this is simpler and safer
for SQLite than parallel writers. The scale section records the exit criteria.

### API surface

All app endpoints require a session except `/health` and the public auth
endpoints (`/auth/me`, `/auth/twitch/authorize`, `/auth/twitch/connect`).
Mutating RPCs for personal data are current-user scoped.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | public | Unchanged |
| GET | `/auth/me` | public | `{authenticated, user?, registration:{open, invite_required}, telegram_bot_configured}`; `user` = `{id, login, display_name, profile_image_url, role, telegram_enabled, telegram_chat_id}` |
| GET | `/auth/twitch/authorize` | public | Authorize URL + redirect URI |
| POST | `/auth/twitch/connect` | public | `{redirect_url, invite_code?}`; sets cookie |
| POST | `/auth/logout` | session | Deletes current session |
| PATCH | `/auth/me` | session | Update `telegram_chat_id`, `telegram_enabled` |
| POST | `/auth/twitch/disconnect` | session | Clear that user's Twitch data |
| GET | `/status` | session | User summary + shared counts + intervals |
| GET | `/games` | session | All catalog games; `selected` is per current user |
| PUT | `/games` | session | Replace current user's selected games |
| GET | `/campaigns` | session | Filtered by current user's games/completions |
| GET | `/streams` | session | Filtered by current user's games/completions |
| GET | `/progress` | session | Current user only |
| POST | `/progress/refresh` | session | Sync current user |
| GET | `/watch-queue` | session | Current user only |
| GET | `/watcher` | session | Current user only |
| PATCH | `/watcher` | session | Current user only |
| POST | `/watcher/focus` | session | Current user only |
| DELETE | `/watcher` | session | Current user only |
| GET | `/twitch/status` | session | Current user's connection, `connected`, `reconnect_required`, `last_error`, `last_synced_at`, expiry, profile |
| POST | `/notifications/test` | session | Send to current user's chat |
| POST | `/scans` | admin | Global catalog/stream scan |
| GET | `/scans/latest` | session | Shared |
| GET | `/admin/users` | admin | Safe user list: id, login, display name, role, active, created/last login, Telegram enabled; never tokens or chat ids |
| PATCH | `/admin/users/{id}` | admin | `{is_active}` only; disabling deletes sessions and stops focus; admins cannot disable themselves |

Error codes: `401` no/expired session, `403` registration closed, bad CSRF, or
not admin, `409` Twitch account conflict, `429` auth rate limit, `400`/`502` keep
current meanings. Authenticated responses use `Cache-Control: no-store`.

### Frontend

- New `AuthGate` around the dashboard. It calls `/auth/me`; unauthenticated users
  see a sign-in screen with the existing Twitch authorize/paste steps and an
  optional invite-code field.
- After a successful connect, the cookie is set, the auth query refreshes, and
  all data queries load for the new user.
- API client sends `credentials: 'include'` and echoes the readable `tdm_csrf`
  cookie in `X-CSRF-Token` on unsafe methods; `VITE_API_TOKEN` is removed.
- All personal query keys include the authenticated user id (for example
  `['u', user.id, 'progress']`). On logout or user change, cancel in-flight
  queries, `queryClient.clear()`, and reset UI state so a shared browser can
  never render the previous user's cache. A `401` does the same and returns to
  the gate.
- Header shows the signed-in user; Profile shows local account details, Twitch
  connection, sign out, and disconnect.
- Settings gains a per-user Telegram section (chat id, opt-in toggle, test) and
  an admin-only Users section. The global "Scan for new drops" action is hidden
  for non-admins.
- Copy that says "there are no local user accounts" is removed. Copy should say
  that the Twitch token is stored on this server for that user's account.
- Existing tabs and visual language stay; this is not a redesign.

### Telegram

- `TELEGRAM_BOT_TOKEN` stays in env. `TELEGRAM_CHAT_ID` is used only to seed the
  migrating owner's chat id; new users set their own.
- `TelegramProvider.configured` means a bot token exists. A new
  `send(message, chat_id=...)` targets a specific chat; there is no global chat
  fallback for regular sends.
- A user receives alerts only when `telegram_enabled` is true and
  `telegram_chat_id` is non-empty. The UI explains how to obtain a chat id and
  offers a test send.
- Disabling Telegram deletes that user's pending `user_campaign_starts` rows, so
  re-enabling later does not send a backlog.
- Provider errors and logs must redact the bot token and never include the
  Telegram request URL. Do not copy provider error text containing URLs into
  user-visible `last_error`.
- A future "message the bot to link automatically" flow can replace the numeric
  field without changing the data model.

### Migration

`init_db()` creates the new tables, then runs a **single-transaction**,
idempotent migration. Both the API and worker call `init_db()`; SQLite's write
lock serializes them, and the first process sets the flag before the second
proceeds.

1. Open one transaction with `BEGIN IMMEDIATE` semantics and check
   `app_meta['multi_user_v1']` inside it. If set, commit and return.
2. If legacy `twitch_auth` exists with a row:
   - Require a non-empty legacy `user_id`. If it is empty, abort the migration
     with a clear operator error: set `OWNER_TWITCH_ID` or fix the row, then
     restart. Do not guess an owner.
   - If `users` is empty, create the owner (role `admin`, active) from the legacy
     `user_id`/`login` and profile.
   - If `users` is non-empty, require a matching `twitch_user_id`; otherwise
     abort rather than attach data to the wrong account.
   - Copy the token into `twitch_accounts`, using `INSERT OR IGNORE`.
   - Set `reconnect_required` when `expires_at` is in the past; seed
     `telegram_chat_id` from `TELEGRAM_CHAT_ID` and enable it when present.
3. Copy `drop_progress`, `progress_snapshots`, `campaign_completions`,
   `watch_focus`, `notifications`, and `campaign_starts` rows into their
   `user_*` counterparts with `INSERT OR IGNORE`/upserts.
4. Copy `games.selected = true` rows into `user_games`.
5. Set `app_meta['multi_user_v1']` and commit in the same transaction.

If there is no legacy token:
- With `OWNER_TWITCH_ID` set and `users` empty, create a placeholder admin user
  with that Twitch id and no token. When that account connects, it claims the
  user row and data.
- Otherwise the first person to connect becomes admin. Operators who care who
  that is should set `OWNER_TWITCH_ID` before removing basic auth.

Legacy tables are not dropped and are frozen after migration. The old owner
signs in once; matching Twitch user id resolves to the migrated row.

**Rollback:** rolling back to the old release makes it read/write the frozen
legacy tables, so data written after migration is invisible. A rollback that
must keep post-upgrade data requires restoring the pre-upgrade backup. Document
and test this runbook.

**Backup:** before deploying, use the WAL-safe `sqlite3 .backup` procedure in
`docs/OPERATIONS.md` (not a live file copy), verify the copy opens, and keep it
until the soak period ends.

### Security and operations

- Session cookies are the only browser auth. No token in frontend bundles.
- `Secure` is derived from the forwarded scheme so public HTTPS gets a secure
  cookie while LAN HTTP development still works.
- nginx basic auth is retired after app auth is verified. `/api` stays private on
  `127.0.0.1:8000`; only the frontend port is public.
- Tokens remain plaintext in the SQLite volume. Do not log them. Telegram
  provider errors are redacted so the bot token never reaches logs. Back up the
  DB before deploying.
- Disabling a user deletes their sessions, disables their focus, and skips them
  in worker loops. It does not delete their rows. Admins cannot disable
  themselves.
- Registration attempts are rate-limited in-process per client IP (for example
  10 attempts/minute, `AUTH_RATE_LIMIT_PER_MINUTE`). Codes must be generated with
  at least 16 random characters; compare with `secrets.compare_digest`. Document
  `openssl rand -base64 24` in `.env.example`.
- `PUBLIC_ORIGIN` and `ALLOWED_HOSTS` pin the production origin when set; the
  same-origin fallback is only for local development.
- Registration code, owner bootstrap, session TTL, and cookie behavior are
  environment settings; update `.env.example`, `docs/OPERATIONS.md`, and
  `docs/DECISIONS.md`.

New settings:

| Setting | Default | Purpose |
|---|---|---|
| `REGISTRATION_CODE` | empty | Shared invite code; empty means closed unless explicitly opened |
| `REGISTRATION_OPEN` | `false` | Intentionally allow new accounts without a code |
| `OWNER_TWITCH_ID` | empty | Bootstrap/claim the first admin when there is no legacy token |
| `SESSION_TTL_DAYS` | `30` | Absolute session lifetime |
| `SESSION_COOKIE_SECURE` | `auto` | `auto` derives from the forwarded scheme; `true`/`false` forces it |
| `PUBLIC_ORIGIN` | empty | Production origin for Origin checks, e.g. `https://pi.taile9ec1c.ts.net` |
| `ALLOWED_HOSTS` | empty | Optional comma list for `TrustedHostMiddleware` |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `10` | Registration/login attempts per client IP per minute |

### Scale

The schema and API are user-keyed, not singleton-based, so growth from a few
friends to a larger group does not require a redesign. The practical ceiling in
this phase is the Pi + one SQLite writer + sequential per-user Twitch calls
(roughly dozens of active users at the current intervals). Beyond that, move the
same schema to Postgres, add per-user scheduling/staggering or a job queue, and
raise the intervals. Those are explicitly later steps, not part of this change.

## Failure modes

| Failure | Behavior |
|---|---|
| Invalid/expired session cookie | `401`; SPA returns to sign-in |
| Invalid/expired Twitch token | Mark `reconnect_required`, show reconnect in UI, skip that user's sync until reconnected; a successful reconnect or sync clears it |
| Global Twitch client misconfigured | Do not set per-user `reconnect_required`; surface the global configuration error |
| One user's progress fetch fails | Log, store `last_error`, continue other users |
| Telegram send fails for one user | Release that user's claims; leave their start rows for retry; redact the bot token; other users unaffected |
| User opts out of Telegram | Delete pending start rows; no backlog if they opt back in |
| Registration code missing on a new account | `403` with a clear message |
| Too many auth attempts | `429` with retry guidance |
| Same browser tries a different Twitch account | `409`; sign out and connect that account separately |
| Browser switches users | All query caches cleared/removed; no previous-user data rendered |
| Migration sees no legacy tables | No-op; fresh install path |
| Migration sees an empty legacy `user_id` or conflicting user | Abort with a clear operator error; no data is assigned by guesswork |
| Rollback to previous release | Legacy tables are frozen; restoring the pre-upgrade backup is required to keep post-upgrade data |

## Testing

- Auth: first-user bootstrap, invite required/valid/invalid, **closed registration
  when the code is empty**, explicit open registration, existing-user login,
  inactive user rejection, different-account conflict, missing `user_id`,
  logout, cookie attributes, absolute expiry, CSRF token required/mismatched,
  `Secure` from forwarded HTTPS, Origin/Host/public-origin cases, and 429 rate
  limiting.
- Expired Twitch token: user is marked `reconnect_required` and skipped; a
  successful reconnect or sync clears it; global config errors do not set it; no
  refresh-token path is exercised.
- Isolation: two users with different games, progress, completions, focus, and
  notification keys never see each other's rows; API-level checks for `/games`,
  `/campaigns`, `/streams`, `/status`, `/progress`, `/watch-queue`, `/watcher`.
- Worker: progress/watcher loops continue after one user fails; scan creates start
  rows only for opted-in users tracking the game; disabling Telegram removes
  pending rows; per-user Telegram target; token redaction on send failure.
- Migration: a legacy fixture produces one owner and copies every personal table;
  no-token bootstrap, empty `user_id`, expired token, conflicting user, partial
  failure/rerun, and concurrent API+worker startup are covered.
- Admin: non-admin gets 403; admin cannot self-disable; disabling revokes
  sessions and stops focus; admin list never exposes tokens.
- Frontend: auth gate, login/logout, cache clearing on user switch, 401 handling,
  per-user settings, admin visibility, build.
- Existing backend suite and ruff must pass; update tests that assumed singletons.
- Run a WAL-safe backup/restore check before migration.

## Rollout

1. Take a WAL-safe backup with the documented `sqlite3 .backup` procedure and
   verify the copy opens.
2. Set `OWNER_TWITCH_ID`, `PUBLIC_ORIGIN`, and a long random
   `REGISTRATION_CODE` (or leave registration closed) in the stack env. Add the
   new settings to `x-backend-env`; remove `API_TOKEN`/`VITE_API_TOKEN`.
3. Deploy the new release with nginx basic auth still enabled. Verify migration
   logs, owner sign-in, old data, a second test user, isolation, per-user
   Telegram, CSRF, and the worker.
4. Remove nginx basic auth and the htpasswd mount; redeploy and verify the public
   HTTPS URL.
5. Verify the public login response sets `Secure` on both cookies, same-origin
   mutations work, and LAN HTTP matches the chosen `SESSION_COOKIE_SECURE`
   behavior.
6. Keep the legacy tables until a later cleanup release after the rollback risk
   has passed. A rollback that must keep new data requires restoring the
   pre-upgrade backup.

## Success criteria

- The existing owner signs in with Twitch once and sees their existing progress,
  games, completions, and focus.
- A new friend joins with the invite code, connects their own Twitch account, and
  sees only their own personal data.
- Two accounts can have different selected games, progress, completions, focus
  targets, and Telegram destinations at the same time.
- Telegram is optional per user; a test message goes only to that user's chat.
- Non-admin users cannot trigger global scans or manage users.
- Unauthenticated requests cannot read personal data; `/health` stays public.
- Backend tests, ruff, and the frontend build pass; docs and ADR are updated.

## Left to the builder

- Exact migration helper placement, provided it is one transaction with the
  documented abort/rollback behavior.
- The shape of auth dependency/helper functions, provided the contracts above
  hold.
- Component/test file layout and naming.
- Whether session cleanup runs in startup, scan, or both (do not add a new
  scheduler dependency).
