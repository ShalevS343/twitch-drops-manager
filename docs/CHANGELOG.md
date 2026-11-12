# Changelog

All notable changes. Dates are ISO (`YYYY-MM-DD`). Newest first.

## Unreleased / planned

- P1 performance: response cache + ETag, `/dashboard` bootstrap endpoint,
  combined `/status` queries.
- P2 performance: materialized dashboard snapshot, explicit relationship loaders,
  background scan job.
- Rotate the Telegram bot token if it appeared in pre-fix logs.

## 2026-11-12

### Integration — multi-user merge and fix wave

- Merged `feat/multi-user` into `main` in `78d2603`. Backend suite: **193
  passed**; `ruff` clean; frontend `npm run build` passes.
- Fix wave: Origin checks accept `PUBLIC_ORIGIN` **or** `CORS_ORIGINS` (LAN
  login/mutations work); default games seed once via `users.games_seeded` so a
  cleared selection stays cleared; disabling an account clears pending campaign
  starts; first-sync background tasks are cancelled on shutdown; frontend shows
  a reconnect warning instead of a green "Synced 0 drops", requires Telegram
  opt-in for tests, and refreshes game-dependent caches.
- **Not deployed.** Production still runs the single-user build; rollout,
  rollback/soak, and the pre-upgrade backup remain pending.
- **Removed the shared nginx basic-auth prompt** from `frontend/nginx.conf` and
  the htpasswd mount from Compose. The public UI is gated by Twitch sign-in and
  the invite code; personal API endpoints still require a session.

### Telegram — auto-link hardening

- Added one-time deep links (`POST /telegram/link`) and a worker long poller for
  `/start`, `/stop`, and `/unlink`; codes are hashed, expire after 10 minutes,
  and work only in private chats.
- `/start` without a code re-enables an already linked chat with "Alerts are on."
  and otherwise replies with the numeric chat id plus Settings instructions.
  `/stop` and `/unlink` copy now points at Settings.
- The poller survives database failures (including offset load/save) and backs
  off exponentially from 5s to 300s; unexpected task termination is logged.
- Manual chat ids are rejected with `409` when another account owns them.
- `POST /telegram/link` returns `bot_username` for Settings copy; `expires_at` is
  always timezone-aware UTC.
- Frontend clears `opener` before opening the bot tab and shows the deep link as
  a fallback when the popup is blocked.
- Backend suite: **227 passed**; `ruff` clean; frontend `npm run build` passes.

### Accounts — multi-user Twitch login + per-user data

- Twitch is now the only identity provider. Added local `users`,
  `user_sessions`, `twitch_accounts`, and `user_*` tables. There are no passwords
  or email accounts; the first user becomes admin.
- Invite-only registration controlled by `REGISTRATION_CODE` and
  `REGISTRATION_OPEN`. Empty code means closed, never open.
- Server-side sessions: opaque `HttpOnly` `tdm_session` cookie with an absolute
  30-day TTL, plus a readable `tdm_csrf` cookie echoed as `X-CSRF-Token` on unsafe
  methods. `SESSION_COOKIE_SECURE=auto` derives `Secure` from the forwarded
  scheme. `API_TOKEN` / `X-API-Token` retired.
- Personal data (selected games, Twitch token/profile, progress, snapshots,
  completions, focus, notifications, campaign starts) is isolated per user.
  Catalog, live streams/matches, and scan runs remain shared and are scanned once.
- Scan queues campaign starts only for users tracking the game and opted into
  Telegram. Progress and watcher jobs loop per active user and isolate failures.
- Per-user Telegram: each user sets a chat id and opt-in; `TELEGRAM_CHAT_ID` only
  seeds the migrating owner.
- Admin endpoints list/enable/disable users and trigger global scans; admins
  cannot disable themselves and never see tokens/chat ids.
- One-time migration copies legacy single-user rows to the owner; legacy tables
  stay frozen for rollback. Rollback that keeps post-upgrade data requires the
  pre-upgrade backup.
- Frontend: auth gate + sign-in screen, cookie/CSRF client, user-scoped query
  keys with cache clearing, per-user Telegram settings, admin Users section,
  admin-only scan action, profile sign-out/disconnect.
- Deployment: new auth env vars in compose and `.env.example`; `API_TOKEN` /
  `VITE_API_TOKEN` removed; nginx preserves inbound `X-Forwarded-Proto`
  (fallback `$scheme`); shared basic auth removed. Public access is Twitch login
  + invite code.
- Docs/ADR: new ADR-019 (supersedes ADR-009) and updates to API, data model,
  backend, architecture, frontend, operations, README, AGENTS, and status.
- **Not deployed.** Production still runs the single-user build until the staged
  rollout in `docs/OPERATIONS.md` is executed.

## 2026-11-07

### UI — mobile dashboard responsiveness

- Fixed the Overview dashboard grid forcing a 630px single-column track on
  phones, which clipped the Needs attention, Next in queue, and Quick actions
  panels. The mobile track is now `minmax(0, 1fr)` and grid items have
  `min-width: 0`.
- The ≤640px navigation is now a burger menu: it opens a vertical tab panel and
  closes on navigation or `Escape`.
- Verified with Playwright at 375px, 390px, and 412px across all tabs, including
  opening the menu.

### Public access — Tailscale Funnel + basic auth

- Frontend nginx now requires HTTP Basic Auth for every route, including
  `/api`.
- The htpasswd file is mounted read-only from the host; no credentials are
  committed. The plaintext password stays in the user's home directory.
- Exposed local port `8282` through Tailscale Funnel at
  `https://pi.taile9ec1c.ts.net`. Funnel was enabled on 2026-11-07 after the
  one-time tailnet action; verified public `401`/`200`.
- API port `8000` is published on `127.0.0.1` only; the frontend reaches it over
  the Compose network.

### Streams — hide completed campaigns

- `GET /streams` now omits completed campaigns from `matching_campaigns` using
  the persisted `campaign_completions` ledger.
- Streams whose only matching campaigns are completed are no longer returned, so
  the Streams page and Overview live count only show actionable streams.
- Added regression coverage for completed-only, mixed, and open-only matches.
  Backend suite: **72 passed**.

### Completed campaigns — tagged and sorted last

- Twitch stops returning a campaign from `dropCampaignsInProgress` once all
  rewards are claimed, so completion is now persisted in `campaign_completions`
  from the Inventory `earnedDropRewards` data (`fetchRewardCampaigns: true`).
- `GET /campaigns` exposes `completed`; completed campaigns show **Completed**
  instead of the catalog status (no more “Active” on finished campaigns), sort
  after unfinished campaigns, and use a green border.
- `GET /progress` appends completed campaigns from the ledger + catalog rewards,
  so Progress and Overview keep them with all drops claimed.
- Added completion-ledger tests. Backend suite: **71 passed**.

### Watch queue — Start watching replaces the timer

- Removed the local watch-session timer, elapsed-time panel, pause/resume controls,
  next-up handoff, `localStorage` session, and related frontend modules/styles.
- Each campaign row now has **Start watching**: it opens the live stream and
  dispatches focus mode to that streamer/campaign (`POST /watcher/focus`).
- Clicking Start watching on another stream replaces the single focus target.
- The Watch queue callout/buttons now describe focus, not a running timer.

### Campaign time uses the largest open drop

- Campaign `remaining_minutes` now uses the **maximum** remaining requirement of
  its unclaimed drops, not the sum. Drop requirements share watch time, so a 1h
  drop + a 2h drop needs 2h, not 3h.
- Applied to `/progress`, `/watch-queue`, the focus watcher target, and the
  Overview/watch-queue displays. Watch-queue urgency sorting across multiple
  campaigns now also uses the largest remaining campaign.
- Added a regression test for the 1h + 2h case.

### Focus watcher — offline/completion alerts, no timer

- Removed the focus panel’s manual-session handoff and timer; the panel is now
  monitor-only and links to the stream.
- The watcher no longer auto-moves to the next live. If the focused live goes
  offline while the campaign still has time, it sends one Telegram alert per
  online session and sets `status=offline`; the target stays until the user picks
  another live or the campaign completes.
- When the focused campaign completes, the watcher sends one completion alert and
  turns focused mode off (`reason=completed`).
- Added `watch-offline:*` and `watch-complete:*` notification dedupe keys, with
  retry on Telegram failure.

### Telegram — no live-stream alerts

- Scan notifications now send **campaign starts only**. New live streams are
  never sent to Telegram, so the bot no longer spams with “Live now” digests.
- Removed the `stream-alert:*` notification key and the stream-digest code path.
- Backend suite: **69 passed**.

### UI — removed automation disclaimers

- Removed the “never plays/controls/simulates watching” notes from the watch
  session and focus watcher panels, the “never claims rewards” copy from the
  connect callouts, and the “read-only” wording in Settings.
- Removed the now-unused `.watch-session-note` styles.

### UI — quick actions alignment

- Overview quick actions now use a two-column grid with equal-width,
  center-aligned buttons; collapses to one column at ≤640px.

## 2026-11-06

### Focused watcher (single focus pointer)

- Added a persisted **focused watcher** over the watch queue: one live
  stream/campaign target at a time (`watch_focus` singleton row, `max_watchers=1`).
- Enable focused mode to auto-pick the most urgent live campaign, manually focus
  any candidate, or click **Next live** to move the watcher to another stream.
- A worker job re-checks every `WATCHER_POLL_SECONDS` (default 60s), notifies when
  the focused live goes offline while the campaign is open, and turns focused mode
  off when the campaign completes.
- Added `GET/PATCH/DELETE /watcher` and `POST /watcher/focus`.
- The watcher is a focus pointer only; offline/completion alerts are described
  below. Backend suite: **68 passed** at the time of the original merge.

### Clearer action labels + ETA removal

- Removed `eta_minutes` from `ProgressDropOut`, `ProgressCampaignOut`, and
  `WatchQueueCampaignOut` (breaking response change) and deleted the ETA
  calculation. Remaining minutes and watch rate are unchanged.
- Progress, watch queue, and overview now show only `X min left`; no “at current
  pace”/ETA text.
- Renamed vague actions to state the verb and object: “Scan for new drops”,
  “Sync drop progress”, “Send test message”, “Track this game”, “Save tracked
  games”, “Start watching”, “Open stream on Twitch”, “Claim on Twitch”, “View
  campaign on Twitch”, “Manage tracked games”.
- Loading labels now match the action (“Scanning…”, “Syncing…”, “Sending…”).

### Manual watch sessions + per-game limits (superseded 2026-11-07)

- Watch queue can start one browser-local watch session for a chosen
  campaign/stream: opens the real Twitch stream, tracks elapsed time, and shows
  progress against the campaign's remaining watch minutes.
- Added pause/resume/stop, persistence in `localStorage` across refreshes, and
  cross-tab sync. Only one session can exist.
- Added campaign-level “Next up” suggestions (most urgent first, best live
  stream) with an explicit **Switch** action; nothing auto-plays or advances.
- The timer is local only: no playback control, heartbeats, or simulated viewing.
- Watch queue and Live streams now group by game and show at most **5 per game**
  by default, with a 5/10/20/All selector and client-side filtering.
- Fixed horizontal page drift on mobile and made only the actual active stream
  show the “Current session” badge.

### Game tracking + campaign-start alerts

- Games can now be tracked by name even when they are absent from the drop
  catalog: `PUT /games` creates missing `Game` rows, and Settings has a
  “Track a game by name” input.
- Scans detect campaigns that become `ACTIVE` for a selected game — a new
  campaign, `UPCOMING` → `ACTIVE`, or the next campaign after the previous one
  ended — and include them in the Telegram digest.
- Added the `campaign_starts` pending ledger: failed Telegram sends are retried on
  the next scan instead of losing the event; the `notifications` claim prevents
  duplicate sends.
- Campaign-start and live-stream events were combined into one digest per scan at
  that time; live-stream Telegram alerts were removed on 2026-11-07.
- Added tests for new/`UPCOMING` starts, add-by-name tracking, untracked-game
  suppression, and retry-after-failure. Backend suite: **58 passed**.

### UI — violet readability pass

- Replaced the amber accent with Twitch violet (`#9146ff`, hover `#a970ff`) and
  white button text.
- Raised text contrast: near-white body copy, brighter muted gray, lighter
  surfaces/borders.
- Larger type scale (15px body, 14px nav, 1.85rem page titles) and sentence-case
  labels; mono is now reserved for numeric/technical data.
- More padding/gaps and fewer micro uppercase labels to reduce clutter.
- Brand mark, favicon, connect icon, empty-state icon, and avatars are circular;
  the favicon is a violet circle with a white gift glyph.
- Verified desktop and mobile screenshots; fixed the System notice wrapping on
  narrow screens.

### Documentation

- Added a complete documentation set: architecture, backend, API, data model,
  frontend, operations, development, decisions, changelog, living status.
- Added `AGENTS.md` with a documentation-update contract for every session.
- Added `README.md` and the docs index.

### UI — solid redesign

- Replaced the purple gradient/glow theme with a solid graphite/amber system.
- Removed all gradients, glows, backdrop blur, and pill-shaped components.
- New custom filled/geometric icon set (no generic outline library).
- Serif display headings, mono data labels, square avatars/badges/progress bars.
- Amber favicon and dark theme color.
- Progress cards now expand to the available width when a single campaign exists.
- Responsive sidebar → horizontal tab bar; verified with headless screenshots at
  desktop and mobile widths.

### Performance — P0

- `/watch-queue`: one flat SQL join instead of loading all campaigns + rewards +
  `raw` JSON. **100.4 → 18.3 ms p50**, **11 → 3 queries**.
- `/streams`: one flat query. **22.6 → 10.1 ms**, **6 → 1 query**.
- `Campaign.raw` is deferred (write-only; ~715 KB not read).
- Twitch profile persisted in `twitch_profile`; `/twitch/status` is DB-only, with
  a non-blocking background warm-up. Cold ~693–821 ms → ~49 ms first request /
  ~8 ms warm.
- Composite index `(drop_id, recorded_at)` on `progress_snapshots`, created on
  existing DBs with `checkfirst`.
- nginx: gzip for API/assets, immutable hashed assets, `no-cache` index, upstream
  keepalive. JS 245.7 → 72.2 KB, `/games` 17.7 → 2.7 KB, watch queue 3.2 → 0.7 KB.
- Initial dashboard load **187 → 89 ms p50** (remaining gap is single-worker
  serialization; P1 `/dashboard` + cache).

### UI — tabbed dashboard

- Sidebar/hash-route tabs: Overview, Campaigns, Progress, Watch queue, Streams,
  Settings, Profile; canonical `#/overview`; mobile horizontal tabs.
- Settings page: game whitelist, scan/refresh/Telegram test, Twitch connection,
  read-only intervals/system status.
- Profile page: Twitch avatar, display name, login, user id, connected since,
  token expiry, reconnect/disconnect. No local user accounts.
- Reusable Twitch connect flow; extracted progress card; toasts; empty/loading/
  error states; skip link and focus states.

### Twitch progress / notifications

- Read-only drop progress from Twitch's internal `Inventory` GraphQL using a
  first-party implicit-login token; profile via `ViewerCard`.
- Device-code flow was abandoned for progress because Twitch GQL rejects
  third-party-app tokens; the implicit grant + pasted redirect is the working path.
- Persisted token in `twitch_auth`; profile cache in `twitch_profile`.
- Watch queue, ETA/rate snapshots, campaign deadline reminders (24h/2h), scoped
  live-stream alerts (later removed on 2026-11-07).
- Telegram: atomic claim-before-send dedupe, one digest per run, claim release on
  failure, ready-to-claim link, `httpx` request logging disabled to stop token
  leakage.

### Catalog / reliability

- Persisted Sunkwi catalog cache; honors `X-RateLimit-Reset`/`Retry-After`; serves
  stale cache on 429/5xx/timeout instead of failing the scan.
- Kuma labels for frontend/API; removed the orphaned Postgres container/volume;
  SQLite is the only database.

### Earlier foundation (same date)

- Split the original single-file app into `backend/` + `frontend/` + `infra/`.
- Switched from Postgres to SQLite; added Homepage labels and the game whitelist.
- Kuma monitoring labels for the manager UI/API.

## Initial

- Project created as a Twitch Drops campaign/stream tracker with Telegram alerts.
