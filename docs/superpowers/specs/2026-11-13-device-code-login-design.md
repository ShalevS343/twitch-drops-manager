# Device-Code Twitch Login — Design

**Date:** 2026-11-13
**Status:** Approved for implementation
**Related:** ADR-003 (first-party client for GQL), ADR-019 (Twitch login)

## Intent

Make Twitch connection work on phones. The current implicit grant redirects to
`https://www.twitch.tv/#access_token=...`; the Twitch mobile app swallows that
URL, so there is no address bar to copy from.

Add a **device-code flow** using Twitch's Smart TV client. The user opens
`https://www.twitch.tv/activate`, enters an 8-character code, and the app creates
the session automatically. No redirect, no token copy.

## Verified spike

The Smart TV client `ue6666qo983tsx6so1t0vnawi233wa` accepts
`POST https://id.twitch.tv/oauth2/device`. A real authorization validated as the
owner account, and Twitch GQL accepted the resulting token with that client id.
A read-only inventory query returned campaign data using the app's normal GQL
headers plus `Client-Id: ue6666qo983tsx6so1t0vnawi233wa`. The Android client
`kd1unb4b3q4t58fwlpcbzcbnm76a8fp` returns `invalid client` for device flow, so
the existing implicit flow must stay on the Android client.

Implementation must verify the first device-flow inventory sync against live
Twitch before calling the feature complete. If that sync fails on headers, make
`TwitchUserProvider._headers()` client-aware (user agent/session/device headers
per client) rather than assuming only `Client-Id` changes.

## Goals

- Primary **Connect Twitch** flow shows a code and activation link on phone or
  desktop; the user never copies a token.
- Existing URL-paste implicit flow remains available as an advanced fallback.
- Existing accounts with Android-client tokens keep working unchanged.
- Each Twitch account stores the client id that issued its token; GQL uses the
  matching `Client-Id`.
- Invite-code registration, first-admin gate, account-switch rules, disabled
  users, sessions, CSRF, rate limits, per-user Telegram, and worker behavior are
  unchanged.
- Existing SQLite databases receive a real, idempotent migration.

## Non-goals

- Removing the implicit flow.
- Refresh-token support (device tokens are stored like current tokens; expiry
  means reconnect).
- A native mobile app or custom URL scheme.
- Per-user Twitch client secrets.
- Changing drop-progress/GQL behavior beyond the client-id header.

## Approaches considered

### A. Smart TV device-code flow — **chosen**

Use Twitch's public Smart TV client for device authorization. Backend starts the
flow, shows `user_code` + `verification_uri`, polls Twitch, then validates the
token and creates the normal app session. The token's Smart TV client id is
stored per account for GQL.

Why: no redirect, works on every phone/browser, no token copy, no third-party
app, and the Smart TV token is accepted by GQL (verified by spike).

### B. Mobile workarounds (disable app links, desktop mode, desktop copy)

Rejected as the primary fix: device/browser-specific, user already reports it is
unreliable, and still requires copying a bearer token.

### C. Register a third-party Twitch app + authorization-code flow

Rejected: callback works, but Twitch GQL rejects third-party tokens for Drops
inventory (ADR-003). The app would lose progress.

## Architecture

### Device login flow

1. Signed-out visitor or signed-in user clicks **Connect with code**.
2. `POST /auth/twitch/device/start`:
   - rate-limited per IP/user;
   - calls Twitch `POST /oauth2/device` with the Smart TV client id and no scopes;
   - stores a short-lived flow row;
   - returns `flow_id`, `user_code`, `verification_uri`, `expires_at`, `interval`.
3. UI shows the code and `https://www.twitch.tv/activate`; user enters the code
   and approves on Twitch.
4. UI polls `POST /auth/twitch/device/poll` with `{flow_id}` every `interval` seconds.
5. Backend polls Twitch's token endpoint with the stored `device_code`:
   - `authorization_pending` → `{status:"pending", interval}`;
   - `slow_down` → increase `interval_seconds`, persist it, return the new
     interval;
   - `expired_token` / `access_denied` → terminal error;
   - success → validate token, run the same user/login/registration logic as the
     implicit flow, store the token + client id, create the session, set cookies,
     return the authenticated user.
   The server enforces at least `interval_seconds` between upstream polls using
   `last_polled_at`, so duplicate tabs or retries cannot violate Twitch's
   `slow_down` cadence. The poll response always includes the current `interval`.
6. UI refreshes `/auth/me` and loads the app.

`/start` accepts `invite_code` for new accounts and is current-user aware for
reconnect. Flow rows are single-use and expire after 30 minutes.

### Data model

#### New column: `twitch_accounts.client_id`

| Column | Type | Notes |
|---|---|---|
| `client_id` | string(64), not null, default `""` | Client that issued the stored token. Empty = legacy row; fall back to the configured Android client id. |

#### New table: `twitch_device_flows`

| Column | Notes |
|---|---|
| `id` | PK |
| `flow_id` | unique random opaque id returned to the browser |
| `device_code` | Twitch device code, short-lived, never returned/logged |
| `user_code` | 8-char code shown to the user |
| `verification_uri` | `https://www.twitch.tv/activate` |
| `client_id` | Smart TV client id used by this flow |
| `invite_code` | optional supplied invite code, short-lived |
| `current_user_id` | nullable; set when started from a signed-in session |
| `interval_seconds` | Twitch polling interval; increased on `slow_down` |
| `last_polled_at` | last upstream token poll, used to enforce the interval server-side |
| `status` | `pending`, `connected`, `denied`, `expired`, `error` |
| `created_at`, `expires_at`, `updated_at` | lifecycle |

Cleanup: expired rows removed on start and during the worker scan.

### Per-account client id

- `TwitchAccount.client_id` stores the token issuer:
  - implicit flow → `settings.device_client_id` (Android);
  - device flow → validated token `client_id` (Smart TV).
- `TwitchUserProvider.fetch_inventory/fetch_profile` accept an optional
  `client_id`; default is `settings.gql_client_id` (Android) for legacy rows.
- `ProgressService` and `ProfileService` pass `account.client_id or default`.
- Existing accounts with empty `client_id` keep working with the Android client.

### API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/twitch/device/start` | public | start flow; body `{invite_code?}` |
| POST | `/auth/twitch/device/poll` | public | poll `{flow_id}`; returns pending or sets cookies + user |
| POST | `/auth/twitch/device/cancel` | public | cancel `{flow_id}` |

Errors: `400` invalid/expired/denied/registration closed, `409` different Twitch
account while signed in, `429` rate limit. `GET /auth/me` is unchanged.

### Frontend

- `AuthPage` and Profile/Settings get **Connect with code** as the primary action.
- The code screen shows the 8-character code with a copy button, the activation
  link, a waiting state, and Cancel.
- Poll at the interval returned by `/start` and every poll response; stop on
  success, cancel, timeout, unmount, or terminal error.
- Persist the pending `{flow_id, user_code, interval}` in `sessionStorage` while
  waiting so a phone tab reload/Twitch-app switch can resume polling. Clear it
  on success, cancel, expiry, or terminal error. If the success response is lost
  after Twitch consumes the code and the session cookie was not set, the user
  starts a fresh code; the UI explains that.
- Keep the existing URL-paste flow under an **Advanced / desktop** disclosure so
  current users and the existing tests are not broken.
- On success, refresh `/auth/me` and invalidate caches exactly as the implicit
  flow does.

### Security

- `flow_id` is a 256-bit opaque bearer value; `device_code` never reaches the
  browser.
- Flow rows are single-use, expire in 30 minutes, and are bound to the supplied
  invite/current user.
- Private authorization only; no client secret is used or stored.
- Device code, user code, tokens, and raw Twitch responses are never logged.
- Per-IP start limits and per-flow polling limits prevent abuse.
- Registration gate is evaluated with the eventual Twitch user id, exactly like
  the implicit flow.

### Migration

`init_db()` keeps `create_all`, then runs an idempotent schema migration inside
the same transaction:

1. `PRAGMA table_info(twitch_accounts)`; if `client_id` is missing:
   `ALTER TABLE twitch_accounts ADD COLUMN client_id VARCHAR(64) NOT NULL DEFAULT ''`.
2. Create the new `twitch_device_flows` table via `create_all`.
3. Record `app_meta['twitch_device_login_v1']='done'`.
4. Leave legacy/multi-user migration behavior untouched.

Fresh DBs get the column from the model; existing DBs get the ALTER. The
migration is safe to re-run and tested against a fixture without the column.

## Testing

- Migration: existing `twitch_accounts` without `client_id` → column added,
  rows preserved, rerun is a no-op.
- Device flow: start, pending, slow_down, success, denied, expired, one-time use,
  cancel, cleanup.
- Login behavior: existing user, new user with/without invite, first-admin gate,
  current-user conflict, disabled user, session cookies.
- Per-client GQL: Android account uses Android `Client-Id`; Smart TV account uses
  Smart TV `Client-Id`; legacy empty client id falls back.
- Implicit flow regression suite stays green.
- Frontend build + manual code screen/activation/poll/success/cancel.
- Full backend suite, ruff, compose config.

## Rollout

1. Backup the DB with the WAL-safe procedure.
2. Deploy with basic auth absent (current state).
3. Verify the ALTER ran once (`PRAGMA table_info`), existing owner still syncs,
   then connect a phone via the code flow.
4. Keep the implicit flow fallback for one soak period; remove it only after the
   code flow is proven.
