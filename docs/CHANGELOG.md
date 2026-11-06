# Changelog

All notable changes. Dates are ISO (`YYYY-MM-DD`). Newest first.

## Unreleased / planned

- P1 performance: response cache + ETag, `/dashboard` bootstrap endpoint,
  combined `/status` queries.
- P2 performance: materialized dashboard snapshot, explicit relationship loaders,
  background scan job.
- Deploy the current `main` (P0 + solid UI) to the live Portainer stack.
- Rotate the Telegram bot token if it appeared in pre-fix logs.

## 2026-11-06

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
  live-stream alerts.
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
