# Status / handoff

Last updated: **2026-11-13**
Source of truth: `main` at the device-code login merge (`5a95d67`), multi-user
merged in `78d2603`, Telegram auto-link in `f1278a8`, link-only chat ID in
`b558ca0`, and security hardening in `5fe3bc7`. The current release is deployed.

## Current state

### Multi-user accounts (deployed)

- Twitch is the only identity provider: no passwords or email accounts. The first
  user becomes `admin` only with a matching `OWNER_TWITCH_ID`, a valid invite
  code, or explicit open registration; later users need `REGISTRATION_CODE`
  unless `REGISTRATION_OPEN=true`.
- Server-side sessions: opaque `tdm_session` (`HttpOnly`, absolute
  `SESSION_TTL_DAYS`), CSRF token in `tdm_csrf` echoed as `X-CSRF-Token`;
  `SESSION_COOKIE_SECURE=true` by default for the public deployment.
  `API_TOKEN` / `VITE_API_TOKEN` retired.
- Security hardening: Twitch client secret moved out of query params/errors;
  scan errors sanitized; first-user bootstrap gated; Telegram link codes cannot
  replace an existing chat; per-user action limits; global auth ceiling; game
  list/name caps; nginx CSP/security headers; frontend binds loopback; `.env.*`
  ignored; `npm ci` and `.dockerignore` added; `details_url` scheme validation.
- Personal data is user-scoped: selected games, Twitch token/profile, progress,
  snapshots, completions, focus, notification claims, campaign starts.
  Catalog (`games`, `campaigns`, `rewards`), streams/matches, and scan runs are
  shared and scanned once.
- Worker scans once, then loops active users for progress and focus; one user's
  token failure sets `reconnect_required` for that user only. Telegram is
  per-user (chat id + opt-in). Profile fetch happens on connect / cold-profile
  background refresh.
- One-time migration copies legacy single-user rows to the owner's account. The
  legacy tables stay frozen; `OWNER_TWITCH_ID` can bootstrap/claim the first
  admin. A pre-upgrade WAL-safe backup is required.
- Frontend: `AuthGate`/sign-in screen, `credentials` + CSRF, user-scoped query
  keys with cache clearing on logout/user change, per-user Telegram settings,
  admin Users list, admin-only scan action, profile/sign-out/disconnect.
- Telegram auto-link: one-time deep links and a worker long poller link a private
  chat from Settings. The poller survives database/provider failures with
  exponential backoff; `/start` re-enables a linked chat. The chat ID is
  read-only — only the link flow can set it; `PATCH /auth/me` only toggles alerts.
- Deployment: compose passes the new auth env vars; `VITE_API_TOKEN` build arg
  removed; nginx preserves inbound `X-Forwarded-Proto`; nginx basic auth has been
  removed. Access is Twitch login + invite code, with `/health` public.
- **Device-code Twitch login is deployed and verified.** The primary Connect
  flow shows an 8-character code and `https://www.twitch.tv/activate`; the
  backend polls Twitch, creates the session, and the first Smart TV inventory
  sync returned 2 campaigns / 8 drops. The existing URL-paste implicit flow is
  still available under Advanced/desktop. `twitch_accounts.client_id` stores the
  issuing client; legacy empty rows fall back to the Android client.
- Docs/ADR updated: API, data model, backend, architecture, frontend, operations,
  decisions (ADR-019, ADR-021), README, AGENTS.

### Validation

- Merged to `main` in `78d2603` (multi-user), `f1278a8` (Telegram auto-link),
  `b558ca0` (link-only chat ID), `5fe3bc7` (security hardening), and `5a95d67`
  (device-code login).
- Backend suite: **307 tests passed** (`pytest -q`); `ruff check app tests` is
  clean.
- Frontend: `npm run build` passes.
- `docker compose --project-directory infra -f infra/docker-compose.yml config -q`
  passes; `nginx -t` passes with the new map.
- The old 71/72-test single-user baseline is superseded; **307** is the current
  floor.

### Live deployment

- **Deployed 2026-11-13 ~00:29 IST** from `main` at `5a95d67` (device-code login
  release). Portainer stack `twitch-drops-manager` (ID 10) pulled that revision;
  backend/frontend images were rebuilt and all three containers recreated.
- The previous security-hardening deploy was 2026-11-12 from `5965da4`.
- Portainer env has `SESSION_COOKIE_SECURE=true`,
  `AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE=120`, and
  `TWITCH_DEVICE_GRANT_CLIENT_ID=ue6666qo983tsx6so1t0vnawi233wa`;
  `PUBLIC_ORIGIN`/`OWNER_TWITCH_ID` remain set.
- Pre-device-login WAL-safe backup:
  `/home/server/twitch-drops-manager-backups/pre-device-login-20261113-022621.db`.
- Migration verified live: `twitch_accounts.client_id` exists,
  `twitch_device_flows` exists, `app_meta.twitch_device_login_v1=done`; existing
  account rows preserved.
- Existing Android-client account still synced before the device test. The live
  device-code flow authenticated `shalevs343`, stored the Smart TV client id
  `ue6666qo983tsx6so1t0vnawi233wa`, and the first inventory sync returned **2
  campaigns / 8 drops**.
- Verified: public URL `200` with no basic-auth challenge; CSP/HSTS/security
  headers present; frontend/API loopback; `/api/v1/health` OK.
- Public URL: `https://pi.taile9ec1c.ts.net` via Tailscale Funnel → local `8282`.
  API stays on `127.0.0.1:8000`.

## Pending work

1. **Soak the device flow**: use the new code flow on a phone for a second
   account, confirm the first inventory sync and reconnect behavior; keep the
   implicit URL-paste flow as Advanced for one soak period.
2. **Kuma**: the frontend no longer listens on `0.0.0.0:8282`. Update the Kuma
   monitor to the public URL/health check or a loopback-aware check.
3. **Rollback/soak**: keep legacy tables until the soak period ends; rollback
   that keeps post-upgrade data requires the pre-upgrade backup. Then plan a
   cleanup release.
4. Rotate the Twitch client secret if a token request failed on the old build
   (the secret could appear in logs/scan errors), and rotate the Telegram bot
   token if it appeared in pre-fix logs.
5. Carry over performance work (P1 response cache/ETag, P2 dashboard snapshot) as
   separate follow-ups; multi-user adds per-user loop cost.

## Known issues / caveats

- **Deployed**: the live stack runs the device-code login release; verify the
  browser checklist above.
- **Device-grant phishing**: a device code is a bearer instruction. Users must
  only enter codes they generated in this app; the UI and docs say so. Device
  login cannot be made phishing-proof by the server.
- **Active poll claims**: `flow_id` is sent in POST bodies (not URLs), and the
  server enforces the Twitch poll interval with an atomic claim.
- **Legacy tokens**: rows with empty `client_id` use the Android/GQL default
  client id; device-login rows use the Smart TV client id.
- **Rollback**: the old release reads frozen legacy tables; keeping post-upgrade
  data requires restoring the pre-upgrade backup.
- **Tokens are plaintext** in `twitch_accounts` inside the SQLite volume.
- **No refresh token** for the implicit grant: an expired token means reconnect;
  the worker skips only that user.
- **SQLite single writer + sequential per-user calls**: practical ceiling is
  dozens of active users on the Pi; Postgres/job queue are later options.
- **Single uvicorn worker**: concurrent requests still serialize.
- **Unofficial Twitch GQL**: can change without notice; first-party client id is
  configurable.
- **Basic auth is temporary** during the rollout; do not treat it as the
  long-term gate.
- `.env` / `.env.save` are local and untracked; never commit them.

## Next session checklist

1. Read [`../AGENTS.md`](../AGENTS.md), this file, and [`README.md`](README.md).
2. `git status -sb`, `git log --oneline -5`; check the live stack before claiming
   deployment state.
3. If deploying: back up `/data/drops.db` first and follow
   [OPERATIONS.md](OPERATIONS.md) deployment runbook.
4. If changing code: implement, tests/lint/build, update docs, update this file.
5. Keep the test baseline here current after each integration run.

## How to update this file

Keep it short. At the end of every session:

- Update **Current state** (commit/deploy/tests).
- Move completed items out of **Pending work**.
- Add/remove **Known issues**.
- Update the date.

Do not include secrets or personal tokens.
