# Operations

## Deployment topology

Production runs on the Raspberry Pi under **Portainer** as stack
`twitch-drops-manager`, from the git repository. The compose source is
[`infra/docker-compose.yml`](../infra/docker-compose.yml).

| Service | Image | Port | Notes |
|---|---|---|---|
| `api` | `twitch-drops-backend:local` | `8000:8000` | FastAPI/uvicorn |
| `worker` | `twitch-drops-backend:local` | — | `python -m app.worker.scheduler` |
| `frontend` | built from `frontend/` | `8282:80` | nginx + SPA |

- Shared named volume: `twitch-drops-manager_drops_data` → `/data` (SQLite
  `/data/drops.db` + `sunkwi_cache.json`).
- The old Postgres `db` service was removed when the project moved to SQLite.
- Compose env comes from `infra/.env` (a symlink to the root `.env` in this
  checkout). Portainer may keep its own copy of the stack configuration.
- Optional labels:
  - Homepage: group/name/icon/href/description.
  - Kuma: `kuma.enable=true`, `kuma.name`, `kuma.port`, `kuma.type=tcp`. The local
    `kuma-sync` container watches Docker labels and creates TCP monitors.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TWITCH_CLIENT_ID` | for streams | — | Helix app client id |
| `TWITCH_CLIENT_SECRET` | for streams | — | Helix app secret |
| `TELEGRAM_BOT_TOKEN` | for alerts | — | Telegram bot token (secret) |
| `TELEGRAM_CHAT_ID` | for alerts | — | Target chat id |
| `DROPS_API_KEY` | optional | empty | Sunkwi API key (rate-limit tier) |
| `DEFAULT_GAMES` | optional | `Rust,Minecraft` | First-run whitelist |
| `POLL_SECONDS` | optional | `900` | Scan interval (min 300) |
| `PROGRESS_POLL_SECONDS` | optional | `300` | Progress interval (min 60) |
| `CORS_ORIGINS` | optional | `http://localhost:5173` | Comma-separated |
| `API_TOKEN` | optional | empty | Require `X-API-Token` on mutations |
| `TWITCH_DEVICE_CLIENT_ID` | optional | built-in first-party client | Advanced progress login override |
| `TWITCH_DEVICE_CLIENT_SECRET` | optional | empty | Advanced |
| `DATABASE_URL` | compose | `sqlite+aiosqlite:////data/drops.db` | do not override casually |

`.env` and `.env.save` are local secrets and must never be committed.

## First-time setup

1. Create a Twitch application at <https://dev.twitch.tv/console/apps>; copy the
   client id/secret into `.env` (used for Helix stream discovery).
2. Optional: create a Telegram bot with @BotFather; put the token in `.env` and
   get the chat id (send `/start`, then inspect `getUpdates` or the bot API).
3. `cp .env.example .env` and fill values.
4. Deploy the stack (Portainer or compose).
5. Open the UI → **Profile → Connect Twitch**, approve, paste the redirect URL.
   This is a one-time read-only authorization; no password is stored.
6. Select games in **Settings → Games** and run **Scan now**.

## Redeploy / upgrade

Portainer:

1. Push/merge to `main`.
2. Portainer → Stacks → `twitch-drops-manager` → **Pull and redeploy**.
3. Verify `/api/v1/health`, the UI, and Kuma monitors.

Manual (same compose project):

```bash
cd /opt/twitch-drops-manager/twitch-drops-manager
docker compose --project-directory infra -f infra/docker-compose.yml up -d --build
```

The DB volume persists. `init_db` adds new tables/indexes on startup. If the
compose project name differs, the volume/network names change; use the existing
project name (`twitch-drops-manager`).

## Health and monitoring

- `GET /api/v1/health` — DB + provider configuration flags.
- `GET /api/v1/status` — last scan, counts, connection state, intervals.
- Kuma monitors (auto-created by `kuma-sync` from labels):
  - `Docker: Twitch Drops Manager` → `192.168.68.113:8282`
  - `Docker: Twitch Drops Manager API` → `192.168.68.113:8000`
- If a monitor is deleted later, `kuma-sync` recreates it from the running
  container labels (after the container is recreated with labels present).

## Logs / diagnostics

```bash
docker ps --filter name=twitch-drops-manager
docker logs --tail 200 twitch-drops-manager-api-1
docker logs --tail 200 twitch-drops-manager-worker-1
docker logs --tail 100 twitch-drops-manager-frontend-1
```

`httpx`/`httpcore` request logging is disabled below WARNING, so bot tokens should
not appear in logs. Rotate the Telegram token if an older log ever exposed it.

## Rate limits / external quotas

| Provider | Limit / behavior |
|---|---|
| Sunkwi catalog | ~1 request / 300s; code caches in memory and `/data/sunkwi_cache.json`, honors reset headers, serves stale during 429/5xx |
| Twitch Helix | app token; normal Helix limits |
| Twitch GQL | internal API; profile cached 10 min in memory, profile persisted in SQLite; token shared across processes |
| Telegram | Bot API; notifications are digests, atomically deduped |

The worker cadence (scan 15m, progress 5m) stays well below the catalog window.

## Backups

Backup the SQLite database (consistent copy via SQLite backup API):

```bash
docker exec twitch-drops-manager-api-1 python - <<'PY'
import sqlite3
src = sqlite3.connect('/data/drops.db')
dst = sqlite3.connect('/data/backup.db')
src.backup(dst)
dst.close(); src.close()
PY
docker cp twitch-drops-manager-api-1:/data/backup.db ./drops-backup.db
docker exec twitch-drops-manager-api-1 rm -f /data/backup.db
```

Restore with the stack stopped: replace `/data/drops.db` in the volume from the
backup; keep a copy of the current file first. See [DATA_MODEL.md](DATA_MODEL.md).

## Security

- Twitch OAuth tokens are stored **plaintext** in SQLite. Protect the volume and
  host access; do not share the DB file.
- Set `API_TOKEN` if the API is reachable by anything you do not trust; mutating
  endpoints (games, scans, progress refresh, Twitch connect/logout, Telegram test)
  then require `X-API-Token`.
- Never commit `.env`/`.env.save`; use `.env.example`.
- Rotate the Telegram bot token if it appears in logs.
- Revoke the Twitch app authorization at Twitch → Settings → Connections if
  needed; then reconnect in the app.
- Read-only boundary: the app never claims drops or automates watching. Do not
  add such behavior.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `429 Too Many Requests` from `drops.sunkwi.com` | catalog limit (1/300s) | P0 cache should serve stale; wait for reset; a cold cache can still fail |
| `Last error: Twitch login expired; reconnect` | token invalid/expired | Profile → Reconnect (paste new redirect URL) |
| Cold load ~800ms on `/twitch/status` | first profile fetch before P0/warm-up | On current code the request is non-blocking; profile appears next poll |
| No live streams | no selected games / no eligible streams / Helix creds missing | Check Settings, `/status`, worker logs |
| Telegram messages missing | token/chat id missing or wrong | Settings → Test Telegram; check worker logs |
| Duplicate Telegram messages | older build before atomic dedupe | Deploy current `main` (digests + atomic claim) |
| Kuma monitor missing | labels absent on running container / `kuma-sync` down | Recreate containers with labels; check `kuma-sync` logs |
| UI shows old assets | browser cache / `index.html` cache | Hard refresh; `index.html` is `no-cache`, hashed assets immutable |
| SQLite `database is locked` | long write / snapshot | Retry; keep writes short; check worker logs |
| `no such column` after deploy | model column added without migration | Use a side table / explicit migration; see DATA_MODEL |

## Rollback

- Container rollback: redeploy the previous commit through Portainer.
- Data: restore the SQLite backup. New tables are additive; older code ignores
  them. Do not downgrade the DB schema without a backup.

## Retention

- Progress snapshots: 24h.
- Streams/matches: replaced each scan.
- Drop progress: replaced each progress sync.
- Campaigns: stale rows deleted on scan.
- Notifications: retained (small); scan runs retained.
