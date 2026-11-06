# API reference

Base path: `/api/v1` (through nginx at `/api/v1` on port 8282, or directly on
port 8000). Interactive OpenAPI: `http://<host>:8000/docs`.

## Conventions

- JSON in/out; `Content-Type: application/json` for bodies.
- **Optional auth:** if `API_TOKEN` is set, mutating endpoints require
  `X-API-Token: <token>`. Read endpoints are public on the LAN/tailnet.
- Timestamps are ISO-8601 strings/datetimes; Twitch campaign end dates keep the
  provider's string form (often with `Z`).
- Errors use FastAPI's `{"detail": "..."}`. Common codes:
  - `400` not configured / invalid token / bad input
  - `401` missing/invalid API token
  - `404` no scans yet
  - `502` upstream provider failure

## Endpoint summary

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | — | Liveness + configured providers |
| GET | `/status` | — | Dashboard summary, intervals, connection state |
| GET | `/games` | — | Games with campaign counts |
| PUT | `/games` | token | Save selected game whitelist (creates missing games) |
| GET | `/campaigns` | — | Campaigns for selected games |
| GET | `/streams` | — | Live matched streams |
| POST | `/scans` | token | Run a catalog/stream scan now |
| GET | `/scans/latest` | — | Latest scan run |
| POST | `/notifications/test` | token | Send a Telegram test message |
| GET | `/progress` | — | Personal drop progress + ETA |
| POST | `/progress/refresh` | token | Sync Twitch inventory now |
| GET | `/watch-queue` | — | Live streams for in-progress campaigns |
| GET | `/watcher` | — | Focused watcher state + dispatchable candidates |
| PATCH | `/watcher` | token | Enable/disable focused mode |
| POST | `/watcher/focus` | token | Manually focus, auto-pick, or move to next live |
| DELETE | `/watcher` | token | Stop the focused watcher |
| GET | `/twitch/status` | — | Connected account/profile state |
| GET | `/twitch/connect` | — | Implicit-login authorize URL |
| POST | `/twitch/connect` | token | Accept pasted redirect URL/token |
| POST | `/twitch/logout` | token | Remove token/profile/progress |

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

## Status

`GET /status`

```json
{
  "app": "Twitch Drops Manager",
  "twitch_configured": true,
  "telegram_configured": true,
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

## Games

`GET /games` → `GameOut[]`

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

`PUT /games` (token)

```json
{ "games": ["War Thunder", "Rust"] }
```

Response: `{ "games": ["War Thunder", "Rust"] }` (names actually selected).

Names are matched case-insensitively and de-duplicated. A name that does not yet
exist in the catalog is created as a tracked `Game` row with no Twitch metadata;
a later scan fills in the game id and box art. This is what allows tracking a game
that currently has no campaign.

When a tracked game's campaign becomes `ACTIVE` (new campaign, `UPCOMING` →
`ACTIVE`, or the first campaign after an earlier one ended), the scan records a
pending campaign-start event and includes it in the next Telegram digest. If
Telegram fails, the event stays pending and is retried on the next scan.

## Campaigns

`GET /campaigns?game=War%20Thunder&status=ACTIVE&active_only=false`

- `game` — exact game name (case-insensitive); omit for all selected games.
- `status` — exact status (upper-cased), e.g. `ACTIVE`.
- `active_only` — only `ACTIVE`.

Returns `CampaignOut[]`:

```json
[{
  "id": 1,
  "external_id": "War Thunder:3df8df9c-...",
  "name": "WTCS Pro Grand Finals",
  "status": "ACTIVE",
  "starts_at": "2026-11-05T10:01:57Z",
  "ends_at": "2026-11-12T09:59:59.999Z",
  "details_url": "https://...",
  "owner_name": "Gaijin",
  "game": { "id": 1, "name": "War Thunder", "...": "..." },
  "rewards": [{
    "id": 1,
    "name": "50% Silver Lion Booster",
    "benefit_name": "50% SL Booster",
    "required_minutes": 30
  }]
}]
```

## Streams

`GET /streams?game=War%20Thunder&live=true`

- `live` defaults to `true`; pass `false` for offline rows (if any).
- Returns `StreamOut[]`, including `matching_campaigns` names.

## Scans

`POST /scans` (token) — runs synchronously (~2–3s). Response:

```json
{ "ok": true, "campaign_count": 118, "stream_count": 5, "notified_count": 0 }
```

Errors: `400` provider not configured, `502` upstream failure. The scan is also
recorded in `scan_runs`.

`notified_count` counts successfully delivered campaign-start and live-stream
events; both are combined into one digest per scan. A campaign start is detected
when a selected game's campaign transitions from any non-`ACTIVE` state to
`ACTIVE`, including a brand-new campaign after the previous one ended. Delivery
failures leave the start pending for the next scan; the notification claim
prevents duplicates.

`GET /scans/latest` → `ScanRunOut`; `404` if no scan has run.

## Notifications

`POST /notifications/test` (token)

- `400` if Telegram is not configured; otherwise sends a test message.
- Response: `{ "sent": true }`.

## Progress

`GET /progress` → `ProgressCampaignOut[]`

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
  "eta_minutes": null,
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
    "rate_minutes_per_hour": 12.0,
    "eta_minutes": null
  }]
}]
```

`POST /progress/refresh` (token)

```json
{ "connected": true, "campaign_count": 1, "drop_count": 7, "notified_count": 0 }
```

Errors: `400` Twitch not connected/expired, `502` GQL/provider failure.

## Watch queue

`GET /watch-queue` → `WatchQueueItemOut[]`, ordered by urgency.

```json
[{
  "stream_id": 1,
  "user_login": "warthunder_esports",
  "user_name": "WarThunder_Esports",
  "title": "WTCS Pro League Grand Finals 2026 | Day 7",
  "viewers": 31029,
  "language": "en",
  "url": "https://www.twitch.tv/warthunder_esports",
  "game_name": "War Thunder",
  "game_box_art_url": "https://...",
  "campaigns": [{
    "campaign_id": "3df8df9c-...",
    "campaign_name": "WTCS Pro Grand Finals",
    "ends_at": "2026-11-12T09:59:59.999Z",
    "remaining_minutes": 1260,
    "eta_minutes": null,
    "next_drop_name": "1 day of Premium",
    "next_drop_remaining_minutes": 12
  }]
}]
```

Returns `[]` when Twitch is not connected or no campaign is in progress.

## Focused watcher

Exactly one watcher can be focused at a time (`max_watchers: 1`). The watcher is
a **queue focus pointer**: it selects one live stream/campaign from the watch
queue and follows it. It never plays a stream, sends watch heartbeats, or
simulates viewing.

`GET /watcher` → `WatchStateOut`

```json
{
  "enabled": true,
  "status": "focused",
  "max_watchers": 1,
  "auto_move": true,
  "focus": {
    "stream_id": 1,
    "user_login": "warthunder_esports",
    "user_name": "WarThunder_Esports",
    "stream_url": "https://www.twitch.tv/warthunder_esports",
    "stream_title": "WTCS Pro League Grand Finals 2026 | Day 7",
    "game_name": "War Thunder",
    "game_box_art_url": "https://...",
    "campaign_id": "3df8df9c-...",
    "campaign_name": "WTCS Pro Grand Finals",
    "target_minutes": 1260,
    "ends_at": "2026-11-12T09:59:59.999Z",
    "reason": "auto",
    "focused_at": "2026-11-06T21:00:00",
    "updated_at": "2026-11-06T21:00:00"
  },
  "candidates": [{
    "stream_id": 2,
    "user_login": "another_channel",
    "user_name": "Another_Channel",
    "stream_url": "https://www.twitch.tv/another_channel",
    "stream_title": "...",
    "game_name": "War Thunder",
    "game_box_art_url": "https://...",
    "viewers": 1200,
    "campaign_id": "3df8df9c-...",
    "campaign_name": "WTCS Pro Grand Finals",
    "target_minutes": 1260,
    "ends_at": "2026-11-12T09:59:59.999Z"
  }],
  "updated_at": "2026-11-06T21:00:00"
}
```

`status` is `idle` (disabled), `focused` (one target selected), or `waiting`
(enabled but no eligible live stream). `candidates` excludes the current focus
and is capped at 8.

`PATCH /watcher` (token)

```json
{ "enabled": true }
```

Enabling auto-selects the most urgent live candidate; disabling clears the focus.
When enabled, the worker re-checks the queue every `WATCHER_POLL_SECONDS` and
moves the focus to the next live stream if the current one goes offline or its
campaign runs out of watch time.

`POST /watcher/focus` (token)

```json
{ "stream_id": 2, "campaign_id": "3df8df9c-...", "strategy": "manual" }
```

- `manual` — both ids are required; the stream/campaign must be in the queue with
  remaining watch time. Replaces the current focus (still one watcher).
- `auto` — picks the most urgent candidate; optional `campaign_id` narrows it.
- `next` — picks another live stream than the current focus; keeps the current
  target with `reason: "next-unavailable"` when no alternative exists.

Invalid/expired targets return `400`. `DELETE /watcher` (token) disables focused
mode and clears the target (same as `PATCH {"enabled": false}`).

## Twitch connection

`GET /twitch/status` → `TwitchUserStatusOut`

```json
{
  "connected": true,
  "login": "shalevs343",
  "user_id": "252776906",
  "expires_at": null,
  "display_name": "shalevs343",
  "profile_image_url": "https://static-cdn.jtvnw.net/...",
  "connected_at": "2026-11-06T18:58:44"
}
```

When no profile row exists, the response is immediate (login-only) and a background
profile fetch is scheduled; the next poll returns the stored profile. No GQL call
is awaited on the request path.

`GET /twitch/connect` → 

```json
{
  "authorize_url": "https://id.twitch.tv/oauth2/authorize?client_id=...&redirect_uri=...&response_type=token",
  "redirect_uri": "https://www.twitch.tv/"
}
```

`POST /twitch/connect` (token)

```json
{ "redirect_url": "https://www.twitch.tv/#access_token=...&scope=&state=..." }
```

Response:

```json
{ "connected": true, "login": "shalevs343", "message": null }
```

- Accepts the full redirect URL or a raw token.
- Rejects tokens issued for a different Twitch client (`400`).
- Stores the token and fetches/stores the profile; runs an initial progress sync.
- The token is read-only in practice (no claim/watch mutations are implemented).

`POST /twitch/logout` (token) — clears `twitch_auth`, `twitch_profile`, and
`drop_progress`. Response `{ "disconnected": true }`.

---

## Caching / rate-limit behavior

- Catalog: persisted cache + in-memory; 1 request/300s provider window; stale
  data is served during 429/5xx/timeouts.
- Progress: no HTTP cache; the worker refreshes every 300s; the UI polls.
- Profile: persisted in SQLite; in-memory GQL cache is only used for the initial
  fetch.
- nginx gzips JSON/JS/CSS and caches hashed assets immutably.

## Breaking-change policy

Prefer additive fields. If a field must change, update `frontend/src/api/types.ts`,
[FRONTEND.md](FRONTEND.md), this file, and the changelog in the same change.
