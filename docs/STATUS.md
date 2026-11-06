# Status / handoff

Last updated: **2026-11-06**
Source of truth: `main` (latest tip at time of writing: `b2acaf7`, plus the
documentation commit that introduced this file — run `git log -1` for exact).

## Current state

### Repository

- `main` includes: P0 performance work, tabbed dashboard, Twitch profile/settings,
  Telegram dedupe/digests, solid graphite/amber UI redesign, favicon.
- Backend tests: **52 passed**; ruff clean.
- Frontend: `npm run build` passes; visually verified with headless screenshots
  (desktop + mobile) against live data.
- Docs: this set was added on top of `b2acaf7`.

### Live deployment (verify before assuming)

The Portainer stack `twitch-drops-manager` was last observed running a build from
**2026-11-06 19:51 UTC**:

- UI asset `index-CKY9jEgc.js` (tabbed dashboard, pre-solid redesign)
- `/watch-queue` still ~100 ms (pre-P0)
- It does include the tabbed UI, Twitch profile, and Telegram digest hotfix

**The live stack is behind `main`.** A redeploy is required to get P0 performance,
the solid UI, the amber favicon, and the latest docs. The DB volume persists.

## Pending work

1. **Redeploy** the Portainer stack (`Pull and redeploy`) to current `main`.
2. **Rotate the Telegram bot token** in @BotFather and update `.env` (the old token
   appeared in logs before request logging was disabled). Redeploy/restart after.
3. Verify after redeploy:
   - `/api/v1/health` and `/api/v1/status`
   - `/watch-queue` p50 (~20 ms on the host; gzip via nginx)
   - UI solid theme + amber favicon
   - Kuma monitors for 8282/8000
4. **P1 performance** (planned): per-endpoint response cache + ETag, `/dashboard`
   bootstrap endpoint, combined `/status` queries. Goal: initial load <50 ms.
5. **P2 performance** (planned): materialized dashboard snapshot written by the
   worker, `lazy="raise"` + explicit loaders, background scan job, frontend code
   splitting.
6. Optional UX: remove duplicate refresh action on the Progress page; add a
   dedicated "session" panel on Profile if useful.

## Known issues / caveats

- **Single uvicorn worker**: concurrent initial requests still serialize; P0
  brings initial load to ~89 ms, P1 needed for <50 ms.
- **SQLite single writer**: fine for one user; do not run multiple workers against
  write-heavy paths without rethinking storage.
- **Unofficial Twitch GQL**: the progress feature relies on Twitch's internal
  `Inventory`/`ViewerCard` and a first-party client id; Twitch can change it.
- **Tokens are plaintext** in `twitch_auth` inside the SQLite volume.
- **Legacy implicit token**: `expires_at` may be null (no expiry known); reconnect
  when Twitch rejects it.
- **Sunkwi limit**: 1 request/300s; cache covers normal operation, a very cold
  cache during a 429 can still surface a provider error.
- **Telegram token exposure**: pre-fix logs contained the bot token; rotate it.
- **Portainer drift**: manual `docker compose` runs use the same project name;
  Portainer may show the stack as out-of-sync until its next redeploy.
- `.env` / `.env.save` are local and untracked; never commit them.

## Next session checklist

1. Read [`../AGENTS.md`](../AGENTS.md), this file, and [`README.md`](README.md).
2. `git status -sb`, `git log --oneline -5`, check live stack.
3. If deploying: back up `/data/drops.db` first (see [OPERATIONS.md](OPERATIONS.md)).
4. If changing code: implement, tests/lint/build, update docs, update this file.
5. If doing P1: update [`backend-performance.md`](backend-performance.md) with
   before/after measurements and [CHANGELOG.md](CHANGELOG.md).

## How to update this file

Keep it short. At the end of every session:

- Update **Current state** (commit/deploy/tests).
- Move completed items out of **Pending work**.
- Add/remove **Known issues**.
- Update the date.

Do not include secrets or personal tokens.
