# Status / handoff

Last updated: **2026-11-07**
Source of truth: `main` (run `git log -1` for the exact tip). Game tracking +
violet UI in `77bfc75`; manual watch sessions + per-game limits in `0eb9b16`;
ETA removal + clearer action labels in `0c6a7e2`; focused watcher in `5e3937e`;
campaign-time math + focus offline/completion alerts in `ea8586d`; Start watching
+ timer removal in `a01f2c9`; completed-campaign tags/ordering in `0db1c07`.

## Current state

### Repository

- `main` includes: P0 performance work, tabbed dashboard, Twitch profile/settings,
  Telegram dedupe/digests, game tracking by name, campaign-start alerts, the
  Start watching → focus action, top-5-per-game live lists, and the violet
  high-contrast UI (circular logo/favicon).
- `main` includes the focused watcher (one queue target at a time,
  manual/auto/next dispatch, offline/completion alerts), sends only campaign-start
  Telegram notifications (no new-live spam), and calculates campaign remaining
  time from the largest open drop. Backend tests: **69 passed**; ruff clean;
  frontend build passes.
- Frontend: `npm run build` passes; visually verified with headless screenshots
  (desktop + mobile) against live data.
- Game tracking: `PUT /games` creates missing `Game` rows, so a game can be
  tracked before it has a campaign. Scans alert when a selected game's campaign
  becomes `ACTIVE`, including `UPCOMING` → `ACTIVE` and the next campaign after a
  previous one ended. Failed Telegram sends retry via `campaign_starts`.
- The Watch queue has no timer: **Start watching** opens the live stream and
  dispatches focus mode to that streamer/campaign. Only one focus target exists;
  clicking another Start watching replaces it. Watch queue/streams are grouped by
  game and capped at 5 by default.
- Completed campaigns (all drops claimed) are tagged **Completed**, sorted after
  unfinished campaigns on Campaigns/Progress/Overview, and use a green border.
- Focused watcher is backend-persisted (`watch_focus`, one row) and reuses the
  watch queue. It notifies when the focused live goes offline while the campaign
  is open, and notifies + turns itself off when the campaign completes. It does
  not auto-move or start a timer.
- ETA was removed from the progress/watch-queue API and UI; remaining minutes are
  shown instead. Action buttons now use explicit verb + object labels.
- Telegram no longer receives new-live-stream alerts at all. Notifications are
  campaign starts plus focused-watcher offline/completion events.
- Campaign remaining time is the maximum open drop requirement, not the sum:
  a 1h + 2h campaign takes 2h. This applies to progress, watch queue, overview,
  and the focused watcher target.
- The UI no longer shows the “never plays/controls/simulates” or “never claims”
  disclaimers; the underlying behavior is unchanged.
- Docs: API, data model, backend, architecture, frontend, decisions, changelog,
  and this file updated for game tracking, Start watching/focus, completed
  campaign ordering/tags, ETA removal, the violet UI pass, the focused watcher,
  Telegram alert changes, and campaign-time math.

### Live deployment (verify before assuming)

The Portainer stack `twitch-drops-manager` was last observed running a build from
**2026-11-06 19:51 UTC**:

- UI asset `index-CKY9jEgc.js` (tabbed dashboard, pre-solid redesign)
- `/watch-queue` still ~100 ms (pre-P0)
- It does include the tabbed UI, Twitch profile, and Telegram digest hotfix

**The live stack is behind `main`.** A redeploy is required to get P0 performance,
the violet UI, the circular favicon, game tracking/campaign-start alerts, Start
watching/focus, the per-game live caps, the focused watcher, and the Telegram
alert changes. The DB volume persists; `campaign_starts` and `watch_focus` are
created automatically by `create_all`. There is no timer state to migrate.

## Pending work

1. **Redeploy** the Portainer stack (`Pull and redeploy`) to current `main`.
2. **Rotate the Telegram bot token** in @BotFather and update `.env` (the old token
   appeared in logs before request logging was disabled). Redeploy/restart after.
3. Verify after redeploy:
   - `/api/v1/health` and `/api/v1/status`
   - `/watch-queue` p50 (~20 ms on the host; gzip via nginx)
   - UI violet theme + circular favicon
   - Settings → Games “Track a game by name” creates a tracked row
   - Watch queue: Start watching opens the stream and focuses that target; no
     timer; top 5 per game
   - Focus watcher: enable, switch focus, Next live, offline alert, completion
     alert + focus off; no auto-move
   - Telegram: campaign starts and focused-watcher alerts only; no new-live spam
   - Campaign remaining time is the largest open drop (1h + 2h shows 2h)
   - Completed campaigns appear last with a green Completed tag on Campaigns,
     Progress, and Overview
   - Live streams: game groups + Per game selector
   - No ETA text; progress shows `X min left` and actions read “Scan for new
     drops” / “Sync drop progress”
   - Overview quick actions are a centered two-column grid (one column on mobile)
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
- **Focused watcher does not auto-move**: an offline target stays in `offline`
  state until the user picks another live or the campaign completes. Offline
  notification is once per online session; completion turns focus off.
- **No Telegram stream alerts**: the scan only notifies campaign starts; live
  streams remain in the watch queue/streams UI.
- **Stream identity is ephemeral**: scans replace `streams` rows, so the watcher
  resolves its target by `user_login` + `campaign_id` and refreshes `stream_id`.
- **API change**: `eta_minutes` was removed from `/progress` and `/watch-queue`
  responses. Remaining minutes and watch rate remain; an external client reading
  ETA must drop that field.
- **No stream digest**: Telegram only receives campaign starts and focused
  watcher events; the `/notifications` ledger still records those keys.
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
