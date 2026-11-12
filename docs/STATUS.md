# Status / handoff

Last updated: **2026-11-12**
Source of truth for this work: the lane branches `feat/multi-user-auth`,
`feat/multi-user-frontend`, and `feat/multi-user-deploy-docs`. `feat/multi-user`
is the integration target and is still at the design/plan commit (`28b1618`)
until the lanes merge; `main` remains the single-user release. Deployment config
and docs are committed on `feat/multi-user-deploy-docs`; nothing is deployed yet.

## Current state

### Multi-user accounts (implemented on the lane branches, **not deployed**)

- Twitch is the only identity provider: no passwords or email accounts. The first
  user becomes `admin`; later users need `REGISTRATION_CODE` unless
  `REGISTRATION_OPEN=true`. Empty code = closed.
- Server-side sessions: opaque `tdm_session` (`HttpOnly`, absolute
  `SESSION_TTL_DAYS`), CSRF token in `tdm_csrf` echoed as `X-CSRF-Token`;
  `Secure` derived from `X-Forwarded-Proto` (`SESSION_COOKIE_SECURE=auto`).
  `API_TOKEN` / `VITE_API_TOKEN` retired.
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
- Deployment: compose passes the new auth env vars; `VITE_API_TOKEN` build arg
  removed; nginx preserves inbound `X-Forwarded-Proto`; basic auth kept for the
  staged rollout.
- Docs/ADR updated: API, data model, backend, architecture, frontend, operations,
  decisions (ADR-019), README, AGENTS.

### Validation

- `docker compose --project-directory infra -f infra/docker-compose.yml config -q`
  passes on `feat/multi-user-deploy-docs`; `nginx -t` passes with the new map.
- Backend `pytest -q` / `ruff` and frontend `npm run build` must pass; the
  backend/frontend lanes run them, and integration must re-run the full suite.
  The old 71/72-test single-user baseline is superseded; use the integration run
  for the current count.

### Live deployment

- **Not deployed.** The Portainer stack `twitch-drops-manager` still runs the
  single-user build from `main`; nginx basic auth is still required on all routes.
- Public URL (when deployed): `https://pi.taile9ec1c.ts.net` via Tailscale
  Funnel → port `8282`; API stays on `127.0.0.1:8000`.
- Staged rollout: backup → set env/owner/registration code → deploy with basic
  auth → verify owner migration, a second user, isolation, Telegram, CSRF, worker,
  Secure cookies → remove basic auth (nginx + compose mount) and verify public
  login.

## Pending work

1. **Integrate and run the full suite** on `feat/multi-user`: backend pytest +
   ruff, frontend build; update this file with the exact pass count/commit.
2. **Deploy stage 1** with the pre-upgrade backup, `OWNER_TWITCH_ID`,
   `PUBLIC_ORIGIN`, `ALLOWED_HOSTS`, `SESSION_COOKIE_SECURE=auto`, and a random
   `REGISTRATION_CODE`. Verify the owner sees old data.
3. **Remove basic auth** (stage 2) after app login is verified; update
   `docs/OPERATIONS.md` if the exact steps change.
4. Keep legacy tables until the soak period ends; then plan a cleanup release.
5. Rotate the Telegram bot token if it appeared in pre-fix logs.
6. Carry over performance work (P1 response cache/ETag, P2 dashboard snapshot) as
   separate follow-ups; multi-user adds per-user loop cost.

## Known issues / caveats

- **Not deployed**: the live stack is single-user until the staged rollout runs.
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
   [OPERATIONS.md](OPERATIONS.md) staged rollout.
4. If changing code: implement, tests/lint/build, update docs, update this file.
5. Update the test baseline here after the integration run.

## How to update this file

Keep it short. At the end of every session:

- Update **Current state** (commit/deploy/tests).
- Move completed items out of **Pending work**.
- Add/remove **Known issues**.
- Update the date.

Do not include secrets or personal tokens.
