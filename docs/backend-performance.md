# Backend Performance Report

**Date:** 2026-11-06
**Environment:** live `twitch-drops-manager` stack on the Raspberry Pi, current `main`, real database
**Data snapshot:** 98 games, 118 campaigns, 437 rewards, 5 live streams, 7 drops in progress
**Method:** 20–30 HTTP samples per endpoint (p50/p95/max), in-process ASGI query counting, SQLite component timings, gzip measurements, nginx header inspection

---

## 1. Executive summary

The backend is **not generally slow**: most endpoints answer in 7–23 ms. The problems are concentrated and fixable:

| Problem | Current | Impact |
|---|---|---|
| `/watch-queue` | **100 ms p50 / 200 ms p95** | Dominates first paint; 11 SQL queries |
| Cold `/twitch/status` | **693 ms** once the 10-minute profile cache expires | Twitch GQL profile call (450–575 ms) |
| Initial Overview load | **187 ms p50 / 288 ms max** (warm) | 6 API calls, **28 SQL queries** |
| No compression | JS 245 KB, `/games` 17.7 KB sent raw | 71–85% avoidable transfer |
| No static cache headers | Hashed JS/CSS revalidated every load | Unnecessary round trips |
| Eager ORM loading | Full campaigns + rewards + 715 KB of unused `raw` JSON loaded for ID/name mappings | 55 ms per full campaign scan |

**Highest-impact, lowest-risk fixes**

1. Rewrite `/watch-queue` with a flat join and no full-campaign loading → **100 ms → ~20 ms, 11 → 3 queries**.
2. Persist the Twitch display name/avatar in the existing `twitch_auth` row → cold `/twitch/status` **693 ms → ~7 ms**.
3. Enable gzip + immutable asset caching in nginx → **JS 245 KB → 72 KB, CSS 28 KB → 6 KB, `/games` 17.7 KB → 2.7 KB**.
4. Defer/remove `Campaign.raw` → ~20 ms saved on every full campaign load, 715 KB not read.
5. Add a short server-side response cache / ETag → repeat polls **< 5 ms**.

**Target after Phase 1 (quick wins):** initial load **~40–60 ms**, watch queue **~20 ms**, cold profile **~7 ms**.
**Target after Phase 2 (cache/materialization):** initial load **< 10 ms**, 1 SQL query, transfer reduced 70–85%.

---

## 2. Current measurements

### 2.1 Endpoint latency (live, warm)

| Endpoint | p50 | p95 | max | Size | SQL queries |
|---|---:|---:|---:|---:|---:|
| `/api/v1/status` | 15.7 ms | 17.7 ms | 18.8 ms | 0.5 KB | 5 |
| `/api/v1/twitch/status` (warm) | 8.9 ms | 12.2 ms | 12.5 ms | 0.3 KB | 1 |
| `/api/v1/twitch/status` (cold cache) | **693 ms** | — | — | 0.3 KB | 1 + GQL |
| `/api/v1/games` | 15.1 ms | 16.7 ms | 112.8 ms | 17.3 KB | 2 |
| `/api/v1/campaigns` | 14.6 ms | 16.2 ms | 19.6 ms | 1.3 KB | 3 |
| `/api/v1/streams` | 22.6 ms | 23.5 ms | 26.9 ms | 2.6 KB | 6 |
| `/api/v1/progress` | 13.3 ms | 14.6 ms | 14.9 ms | 2.9 KB | 2 |
| `/api/v1/watch-queue` | **100.4 ms** | **200.6 ms** | **216.9 ms** | 3.1 KB | **11** |
| `/api/v1/health` | 7.2 ms | 9.5 ms | 9.9 ms | 0.1 KB | 1 |

**Initial Overview load (6 requests in parallel): 187 ms p50, 288 ms max.**
On a cold Twitch profile cache it becomes ~700 ms because `/twitch/status` is on the critical path.

### 2.2 What the frontend requests

On first load:

- `App.tsx`: `/status`, `/twitch/status`
- `OverviewPage`: `/campaigns`, `/progress`, `/streams`, `/watch-queue`
- Total: **6 requests / 28 SQL queries**

Polling afterwards:

- `/status` every 30 s
- `/watch-queue` every 30 s
- `/progress` every 60 s
- `/twitch/status` every 60 s

`/games` is only requested by the Settings tab.

### 2.3 Transfer size

| Asset / payload | Raw | gzip -9 | Saving |
|---|---:|---:|---:|
| JS bundle | 245.7 KB | 71.9 KB | 71% |
| CSS bundle | 27.7 KB | 6.3 KB | 78% |
| `/api/v1/games` | 17.7 KB | 2.7 KB | 85% |
| `/api/v1/watch-queue` | 3.2 KB | 0.7 KB | 79% |

The live nginx responses currently have **no `Content-Encoding`** and **no `Cache-Control`** on hashed assets. Nginx is shipping the full JS/CSS/JSON uncompressed.

---

## 3. Root causes

### 3.1 `/watch-queue`: 11 queries and 100 ms

Component measurements inside the live container:

| Step | Time | Why |
|---|---:|---|
| `CampaignRepository.list_all()` | **55 ms** | Loads all 118 full `Campaign` ORM rows, including 715 KB of `raw` JSON and eager `game` + `rewards` (3 queries, 437 rewards) |
| `StreamRepository.list(live=True)` | **18 ms** | Loads full `Campaign` + rewards for each matched stream (4 queries) |
| `ProgressRepository.list()` | 2 ms | 7 rows |
| `snapshots_since()` | 3.6 ms | 42 rows |
| Build + Pydantic serialization | ~20 ms | 5 items |
| **Total** | **~100 ms** | **11 queries** |

The endpoint only needs `campaign.id / external_id / name / ends_at` to map GQL campaign IDs. It loads the entire campaign graph instead.

**Measured alternatives:**

- Full `select(Campaign)`: **55 ms**
- Lightweight `select(id, external_id, name, ends_at)`: **2.9 ms**
- Flat join of streams + matches + campaigns: **2.7 ms** vs **18 ms** ORM relationship loading

A flat-query watch queue should land around **15–25 ms**.

### 3.2 `/streams`: 6 queries for 5 rows

Same eager-loading pattern: it loads campaigns + rewards + games for campaign matches even though the response only needs campaign **names**.

- Current ORM relationship shape: 18 ms
- Flat join: **2.7 ms**

Expected endpoint: **~8 ms**.

### 3.3 `/status`: 5 queries, 16 ms

Queries: selected games, campaign count, stream count, latest scan, auth row.
The two counts together cost only ~4 ms; the rest is ORM/serialization. Low priority, but can be combined into one SQL statement with scalar subqueries (~3 ms) or cached.

### 3.4 Cold `/twitch/status`: 693 ms

The profile (display name + avatar) is fetched from Twitch GQL (`ViewerCard`) with a 10-minute in-memory cache.

- Warm: 7–9 ms (1 DB query)
- Cold: **693 ms** (GQL profile call measured at 450–575 ms)

This is the worst perceived latency because it happens on first load after the cache expires or after a restart. The data changes rarely.

### 3.5 Eager relationships everywhere

`Campaign.game` and `Campaign.rewards` are `lazy="selectin"`, as are `Stream.game`, `Stream.matches`, and `StreamCampaignMatch.campaign`. Any `select(Campaign)` or `select(Stream)` silently pulls a large graph. This is the source of the query fan-out (11/6/5) and the 55 ms campaign load.

`Campaign.raw` is **715,784 bytes** for 118 rows and is only ever **written** (`repositories/campaigns.py:100`). No read path uses it.

### 3.6 No HTTP caching or compression

- nginx has no `gzip` directive; the JS/CSS/JSON are uncompressed.
- Hashed assets have only `ETag`/`Last-Modified`; no `Cache-Control: immutable`, so they are revalidated on every load.
- API GETs have no `ETag`/`Cache-Control`; every 30–60 s poll recomputes the same data.
- nginx proxies to `api:8000` without upstream keepalive (`proxy_http_version 1.1` + `Connection ""` absent).

### 3.7 Head-of-line blocking

The API runs a single uvicorn worker. The 100 ms watch-queue request (ORM + serialization) blocks the event loop, which is why the 6 concurrent initial requests take 187 ms instead of ~max(endpoint) = 100 ms. Caching/materialization fixes this more effectively than adding workers.

### 3.8 Minor

- `progress_snapshots` has an index on `drop_id` only, while the query filters `drop_id IN (...) AND recorded_at >= ...`. A composite `(drop_id, recorded_at)` index is cheap hygiene.
- `/campaigns` is small today because only one game is selected; with many selected games it will grow with full campaign + rewards + raw payloads.
- Manual `POST /scans` is synchronous (~3.2 s from the last scan run) and blocks the request. Not a first-load issue, but a UX one.

---

## 4. Fixes, prioritized

### P0 — Quick wins (low risk, high impact)

#### 1. Flat watch-queue query (S)
Replace `CampaignRepository.list_all()` + `StreamRepository.list()` with:

- lightweight campaign mapping (`id, external_id, name, ends_at`) or none at all;
- one flat join for streams → matches → campaigns → games (stream fields + campaign `external_id/name/ends_at` + game name/art);
- group repeated rows in Python.

Expected: **100 ms → ~20 ms**, **11 → 3 queries**.

#### 2. Light streams query (S)
Same flat-join pattern for `/streams`; only load campaign names/GQL IDs. Expected **22 ms → ~6–8 ms**, **6 → 2 queries**.

#### 3. Defer or remove `Campaign.raw` (S–M)
`raw` is write-only. Add `deferred=True` to the column (or move it to a side table / stop storing it). This avoids ~20 ms and 715 KB on every full campaign load. Verify no test reads `.raw`.

#### 4. Persist Twitch profile (S–M)
Add `display_name` and `profile_image_url` to the existing `twitch_auth` row, populated during `/twitch/connect` (no new user table). `/twitch/status` then reads the DB only. Optionally refresh it daily in the worker.

Expected cold `/twitch/status`: **693 ms → ~7 ms**. This removes the worst cold-start latency.

#### 5. nginx compression + static caching + keepalive (S)
- `gzip on` for JSON/JS/CSS/SVG.
- `/assets/`: `Cache-Control: public, max-age=31536000, immutable`.
- `/index.html`: `no-cache`.
- Upstream `keepalive 32`, `proxy_http_version 1.1`, `Connection ""`.

Expected: 70–85% less transfer; faster repeat loads; fewer TCP handshakes.

#### 6. Composite snapshot index (S)
`CREATE INDEX ix_progress_snapshots_drop_recorded ON progress_snapshots(drop_id, recorded_at)`.
Minor today (42 rows), important as snapshots grow.

### P1 — Response caching and fewer round trips (1–2 days)

#### 7. Server-side cache + ETag (M)
Cache serialized GET responses for 10–30 s, keyed by path, with invalidation on scan/progress sync (or a data-version counter). Add `ETag` and `Cache-Control: private, max-age=10, stale-while-revalidate=30`.

Expected repeat polls: **< 5 ms**, near-zero DB work; 304s or browser-cache hits.

#### 8. `/dashboard` bootstrap endpoint (M)
Return status + Twitch profile + progress + watch queue + streams in one response, built from one DB session/cache. Frontend initial load becomes **1 request** instead of 6, with one consistent snapshot.

#### 9. Combine `/status` queries (S)
One statement with scalar subqueries, or cache `/status` for 10 s. Minor (~1–2 ms), but easy.

### P2 — Architectural (early project, recommended before scale)

#### 10. Materialized dashboard snapshot (M–L)
A `dashboard_cache` table (`id=1`, `payload` JSON, `updated_at`, `version`) written by the worker after each scan/progress sync (and on manual refresh). `GET /dashboard` returns one row; ETag from `version`.

Expected: **28 SQL queries → 1**, initial server time **< 10 ms**, watch queue **< 5 ms**. Trade-off: up to one worker interval of staleness (5–15 min; manual refresh/scan recomputes).

#### 11. `lazy="raise"` + explicit loaders (M)
Change eager `selectin` relationships to `lazy="raise"` and load only what each query needs (`selectinload`/`load_only`). This prevents future N+1 regressions and makes query cost explicit. Do it after the flat-query fixes so behavior is covered by tests.

#### 12. Background scan job (M)
Make `POST /scans` enqueue work and return `202` + job id; frontend polls job status. The scan is ~3.2 s and currently ties up a request. Not a first-load issue, but better UX.

#### 13. Postgres/multiple workers (L, only if multi-user)
SQLite + one uvicorn worker is correct for a single-user Pi. If this becomes multi-user or write-heavy, move to Postgres and run multiple workers; the caching/materialized read model would carry over.

#### 14. Frontend code splitting (M)
Lazy-load Settings/Profile/Streams/Campaigns with `React.lazy`; the initial bundle drops from ~245 KB to the Overview + shared shell. Combine with asset caching.

---

## 5. Expected results

| Metric | Now | After P0 | After P1/P2 |
|---|---:|---:|---:|
| Initial load (warm) | 187 ms p50 | ~40–60 ms | < 10 ms |
| Initial load (cold profile) | ~700 ms | ~40–60 ms | < 10 ms |
| `/watch-queue` p50 | 100 ms | ~20 ms | < 5 ms (cached) |
| `/watch-queue` p95 | 200 ms | ~50 ms | < 10 ms |
| Cold `/twitch/status` | 693 ms | ~7 ms | ~7 ms |
| SQL queries per initial load | 28 | ~12–17 | 1 |
| JS transfer | 245.7 KB | 71.9 KB gzip | 71.9 KB cached |
| `/games` transfer | 17.7 KB | 2.7 KB gzip | 2.7 KB cached |

---

## 6. Recommended sequence

1. **P0 first (about half a day):** watch queue flat query, streams flat query, defer `raw`, persist Twitch profile, nginx gzip/static cache/keepalive, snapshot index. Re-run this benchmark.
2. **P1 next (1–2 days):** response cache + ETag, `/dashboard` endpoint, combined status query.
3. **P2 after (2–4 days):** materialized dashboard snapshot, `lazy="raise"` + explicit loaders, background scan job.

If only three things are done, do **profile persistence**, the **watch-queue flat query**, and **nginx gzip + immutable assets** — those cover the two worst user-perceived latencies and the largest transfer waste.

---

## P0 results (implemented 2026-11-06)

Measured on a test container with a copy of the live database, same benchmark:

| Metric | Before P0 | After P0 |
|---|---:|---:|
| `/watch-queue` p50 | 100.4 ms | **18.3 ms** |
| `/watch-queue` p95 | 200.6 ms | **18.6 ms** |
| `/streams` p50 | 22.6 ms | **10.1 ms** |
| Initial load p50 | 187.3 ms | **89.1 ms** |
| Initial load p95 | 288.2 ms | **105.8 ms** |
| Cold `/twitch/status` | 693–821 ms | **48.7 ms first request**, 8.4 ms warm |
| SQL queries `/watch-queue` | 11 | **3** |
| SQL queries `/streams` | 6 | **1** |
| SQL queries initial load | 28 | **~16** |
| `/games` transfer | 17,684 B | **2,694 B gzip** |
| JS bundle transfer | 245,748 B | **72,187 B gzip** |
| CSS transfer | 27,670 B | **6,275 B gzip** |

Implemented: flat watch-queue/streams queries, deferred `Campaign.raw`, persisted Twitch profile with non-blocking background warm-up, composite snapshot index, nginx gzip + immutable assets + upstream keepalive.

The remaining 89 ms initial load is single-worker serialization of the six concurrent requests. P1 (`/dashboard` + response cache/materialization) is required to reach <50 ms.

---

## 7. Appendix — key code locations

- Watch queue: `backend/app/api/v1/watch_queue.py`
- Campaign loading: `backend/app/repositories/campaigns.py:64` (`list_all`)
- Stream loading: `backend/app/repositories/streams.py`
- Eager relationships / raw column: `backend/app/domain/models.py:51-53, 92-94, 120, ~40`
- Twitch profile: `backend/app/api/v1/progress.py:135`, `backend/app/providers/twitch_user.py:180`
- Status queries: `backend/app/api/v1/status.py`
- SQLite pragmas: `backend/app/core/db.py`
- Snapshot model: `backend/app/domain/models.py:180`
- nginx: `frontend/nginx.conf`
- Initial requests: `frontend/src/App.tsx`, `frontend/src/pages/OverviewPage.tsx`, `frontend/src/hooks/useApi.ts`
