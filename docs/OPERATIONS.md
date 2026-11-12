# Operations

## Deployment topology

Production runs on the Raspberry Pi under **Portainer** as a **Git-based** stack
`twitch-drops-manager`, cloning
`https://github.com/ShalevS343/twitch-drops-manager.git` (`main` branch,
`infra/docker-compose.yml`). Do not edit the stack compose in Portainer; change
the repo and use **Pull and redeploy**.

| Service | Image | Port | Notes |
|---|---|---|---|
| `api` | `twitch-drops-backend:local` | `127.0.0.1:8000` | FastAPI/uvicorn |
| `worker` | `twitch-drops-backend:local` | — | `python -m app.worker.scheduler` |
| `frontend` | built from `frontend/` | `8282:80` | nginx + SPA |

- Shared named volume: `twitch-drops-manager_drops_data` → `/data` (SQLite
  `/data/drops.db` + `sunkwi_cache.json`).
- Portainer stack environment is the source for runtime secrets. Local
  `infra/.env` (a symlink to the root `.env`) is only for local runs; never
  commit either.
- Only port `8282` is public. The API is published on loopback and reached by
  nginx over the Compose network.
- Labels:
  - Homepage: group/name/icon/href/description (Homepage discovers these).
  - Kuma: none required. `kuma-sync` auto-creates monitors for every running
    container except `kuma-sync`/`uptime-kuma`.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TWITCH_CLIENT_ID` | for streams | — | Helix app client id (shared) |
| `TWITCH_CLIENT_SECRET` | for streams | — | Helix app secret |
| `TELEGRAM_BOT_TOKEN` | for alerts | — | One bot token for all users (secret) |
| `TELEGRAM_CHAT_ID` | optional | empty | **Seed only** for the migrating owner; not a global recipient |
| `DROPS_API_KEY` | optional | empty | Sunkwi API key (rate-limit tier) |
| `DEFAULT_GAMES` | optional | `Rust,Minecraft` | New-user default whitelist |
| `POLL_SECONDS` | optional | `900` | Scan interval (min 300) |
| `PROGRESS_POLL_SECONDS` | optional | `300` | Per-user progress interval (min 60) |
| `WATCHER_POLL_SECONDS` | optional | `60` | Per-user focus reconcile interval (min 30) |
| `REGISTRATION_CODE` | optional | empty | Shared invite code; **empty = closed**, never open |
| `REGISTRATION_OPEN` | optional | `false` | Explicitly allow signup without a code |
| `OWNER_TWITCH_ID` | recommended | empty | Bootstrap/claim the first admin |
| `SESSION_TTL_DAYS` | optional | `30` | Absolute session lifetime |
| `SESSION_COOKIE_SECURE` | optional | `auto` | `auto` (forwarded scheme), `true`, or `false` |
| `PUBLIC_ORIGIN` | production | empty | Origin for Origin/Host checks, e.g. `https://pi.taile9ec1c.ts.net` |
| `ALLOWED_HOSTS` | recommended | empty | Comma-separated Host allowlist for `TrustedHostMiddleware` |
| `AUTH_RATE_LIMIT_PER_MINUTE` | optional | `10` | Registration/login attempts per IP per minute |
| `CORS_ORIGINS` | optional | `http://localhost:5173` | Comma-separated; local dev only |
| `TWITCH_DEVICE_CLIENT_ID` | optional | built-in first-party client | Advanced progress login override |
| `TWITCH_DEVICE_CLIENT_SECRET` | optional | empty | Advanced |
| `DATABASE_URL` | compose | `sqlite+aiosqlite:////data/drops.db` | do not override casually |
| `DROPS_AUTH_FILE` | staged | `/home/server/twitch-drops-auth/htpasswd` | Host basic-auth file; remove after stage 2 |

`.env` and `.env.save` are local secrets and must never be committed.
`API_TOKEN` and `VITE_API_TOKEN` are retired; remove them from the stack env.

## First-time setup

1. Create a Twitch application at <https://dev.twitch.tv/console/apps>; copy the
   client id/secret into `.env` (used for shared Helix stream discovery).
2. Optional: create a Telegram bot with @BotFather; put the token in `.env`.
   Each user supplies their own chat id in Settings → Telegram.
3. Set `OWNER_TWITCH_ID` to the numeric Twitch id that should own the migrated
   data/first admin (see below), `PUBLIC_ORIGIN` to the public URL, and
   `ALLOWED_HOSTS` to the hostnames that should be accepted.
4. Set a long random `REGISTRATION_CODE` (`openssl rand -base64 24`) if friends
   should be able to join, or leave it empty for a closed deployment.
5. `cp .env.example .env` and fill values; deploy the stack.
6. Open the UI → sign in with Twitch, approve, paste the redirect URL. The first
   user becomes admin; later users need the invite code.
7. Select games in **Settings → Games** and run **Scan for new drops** (admin).

There is no password to set or reset. A user who signs in with a different Twitch
account gets a different local account; sign out first.

## Upgrade to multi-user (staged rollout)

Deployment is **not performed** by this change. Run this runbook when deploying.

### 1. Back up before upgrading

Use the WAL-safe backup procedure below (SQLite `.backup`, not a live file copy).
Verify the copy opens and keep it until the soak period ends.

```bash
docker exec twitch-drops-manager-api-1 python - <<'PY'
import sqlite3
src = sqlite3.connect('/data/drops.db')
dst = sqlite3.connect('/data/backup.db')
src.backup(dst)
dst.close(); src.close()
PY
docker cp twitch-drops-manager-api-1:/data/backup.db ./drops-backup-pre-multiuser.db
docker exec twitch-drops-manager-api-1 rm -f /data/backup.db
docker run --rm -v "$PWD":/b twitch-drops-backend:local \
  python -c "import sqlite3; c=sqlite3.connect('/b/drops-backup-pre-multiuser.db'); print(c.execute('pragma integrity_check').fetchone())"
```

Find the owner's numeric Twitch id (do **not** print the token):

```bash
docker exec twitch-drops-manager-api-1 python - <<'PY'
import sqlite3
row = sqlite3.connect('/data/drops.db').execute(
    'select user_id, login from twitch_auth limit 1').fetchone()
print(row)
PY
```

If the legacy `user_id` is empty, fix it or set `OWNER_TWITCH_ID` before
deploying. The migration aborts rather than guessing an owner. If there is no
legacy token, either set `OWNER_TWITCH_ID` for a placeholder admin or let the
first sign-in become admin.

### 2. Set the new stack environment

In Portainer (or local `.env`): add `REGISTRATION_CODE`, `REGISTRATION_OPEN`,
`OWNER_TWITCH_ID`, `SESSION_TTL_DAYS`, `SESSION_COOKIE_SECURE`, `PUBLIC_ORIGIN`,
`ALLOWED_HOSTS`, and `AUTH_RATE_LIMIT_PER_MINUTE`. Remove `API_TOKEN`. Keep the
nginx basic-auth htpasswd mount for this stage.

For the public Pi:

```text
OWNER_TWITCH_ID=<numeric id>
PUBLIC_ORIGIN=https://pi.taile9ec1c.ts.net
ALLOWED_HOSTS=pi.taile9ec1c.ts.net,localhost,127.0.0.1
SESSION_COOKIE_SECURE=auto
SESSION_TTL_DAYS=30
AUTH_RATE_LIMIT_PER_MINUTE=10
REGISTRATION_CODE=<openssl rand -base64 24>
REGISTRATION_OPEN=false
```

### 3. Deploy stage 1 (basic auth still on)

Pull and redeploy. Then verify:

1. API/worker logs show no migration abort. Confirm the flag:

   ```bash
   docker exec twitch-drops-manager-api-1 python - <<'PY'
   import sqlite3
   c = sqlite3.connect('/data/drops.db')
   print(c.execute("select value from app_meta where key='multi_user_v1'").fetchone())
   print(c.execute("select count(*) from users").fetchone())
   print(c.execute("select count(*) from user_games").fetchone())
   PY
   ```

2. The owner signs in with Twitch and sees their existing games, progress,
   completions, and focus.
3. A second test user joins with the invite code, connects their own Twitch
   account, and sees only their own personal data.
4. Isolation: the two users can have different games, progress, focus, and
   Telegram destinations at the same time.
5. Telegram: set a chat id in Settings → Telegram, opt in, send a test; only that
   user receives it. Campaign starts go only to opted-in tracking users.
6. CSRF: after login, `tdm_session` is `HttpOnly`; `tdm_csrf` is readable; unsafe
   requests send `X-CSRF-Token`. A missing/mismatched token returns `403`.
7. Worker: progress syncs both users; one bad token marks only that user
   `reconnect_required` and other users continue.
8. Header/HTTPS: the public login sets `Secure` on both cookies (see below).

### 4. Deploy stage 2 (remove basic auth)

After stage 1 is verified, remove the outer gate in the repo:

1. In `infra/docker-compose.yml`, delete the frontend htpasswd `volumes:` entry
   (and the `DROPS_AUTH_FILE` setting).
2. In `frontend/nginx.conf`, delete `auth_basic` and `auth_basic_user_file`.
3. Pull and redeploy (the frontend image must be rebuilt for nginx changes).
4. Verify the public HTTPS URL works without basic-auth credentials and app login
   is required.

Keep the host htpasswd/password files until the soak period ends; they are no
longer used by the container.

### 5. Cookie / proxy verification

Tailscale Funnel terminates TLS and sends `X-Forwarded-Proto: https`; nginx
preserves only `http`/`https` and falls back to `$scheme`. With
`SESSION_COOKIE_SECURE=auto`, the login response should set `Secure` on
`tdm_session` and `tdm_csrf` on the public URL.

Check in a browser: DevTools → Application → Cookies shows `tdm_session`
(HttpOnly, Secure, SameSite=Lax) and `tdm_csrf` (readable, Secure). Also inspect
the Network request headers for `X-CSRF-Token` on a save/test action.

If the cookie is not `Secure` on HTTPS:

- confirm Funnel still sends `X-Forwarded-Proto` (or set
  `SESSION_COOKIE_SECURE=true` for a public HTTPS-only deployment);
- inspect the generated nginx config with
  `docker exec twitch-drops-manager-frontend-1 nginx -T | grep -A3 forwarded_proto`;
- do not work around it by disabling `Secure` on the public URL.

LAN HTTP development can use `SESSION_COOKIE_SECURE=false`; do not use that on
the public host.

## Registration management

| Goal | Action |
|---|---|
| Invite friends | Set `REGISTRATION_CODE` to a long random value and redeploy |
| Close registration | Clear `REGISTRATION_CODE` and keep `REGISTRATION_OPEN=false` |
| Rotate the invite | Replace the code and redeploy; existing sessions/users stay |
| Intentionally open signup | Set `REGISTRATION_OPEN=true` (not recommended on a public URL) |
| Stop one user | Sign in as admin → Settings → Users → disable |

Disabling a user deletes their sessions, disables their focus, and skips them in
worker loops; their rows are kept. Admins cannot disable themselves.

## Redeploy / upgrade

Portainer (production):

1. Push/merge to `main`.
2. Portainer → Stacks → `twitch-drops-manager` → **Pull and redeploy**.
3. Verify `/api/v1/health`, the UI, and Kuma monitors.
4. For the multi-user release, follow the staged rollout above (backup first).

Do not edit the stack compose in Portainer or run a manual `docker compose up`
against production; the stack is Git-backed.

Local-only validation (not production):

```bash
cd /opt/twitch-drops-manager/twitch-drops-manager
docker compose --project-directory infra -f infra/docker-compose.yml up -d --build
```

The DB volume persists. `init_db` adds new tables/indexes and runs the one-time
migration. If the compose project name differs, volume/network names change; use
the existing project name (`twitch-drops-manager`).

## Public access (Tailscale Funnel)

Public access is through Tailscale Funnel at
`https://pi.taile9ec1c.ts.net`, proxying local port `8282`.

- During stage 1, nginx still requires HTTP Basic Auth for every route, including
  `/api`.
- Username: `admin`
- Password file: `/home/server/twitch-drops-auth/password.txt` (mode `600`)
- htpasswd file: `/home/server/twitch-drops-auth/htpasswd` (mode `644`, mounted
  read-only; hash only, not committed)
- Rotate the password:

  ```bash
  PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
  printf 'admin:%s\n' "$(openssl passwd -apr1 "$PASSWORD")" \
    > /home/server/twitch-drops-auth/htpasswd
  printf '%s\n' "$PASSWORD" > /home/server/twitch-drops-auth/password.txt
  chmod 644 /home/server/twitch-drops-auth/htpasswd
  chmod 600 /home/server/twitch-drops-auth/password.txt
  docker restart twitch-drops-manager-frontend-1
  ```

- Re-enable Funnel after a reset with: `sudo tailscale funnel --bg 8282`
- Only port `8282` is public. The API is loopback-only.
- Basic auth is temporary; stage 2 removes it. The app's Twitch login and
  `SESSION_COOKIE_SECURE` are the long-term gate.

## Health and monitoring

- `GET /api/v1/health` — public; DB + provider configuration flags.
- `GET /api/v1/status` — signed-in summary, last scan, per-user counts.
- Kuma monitors (auto-created by `kuma-sync`):
  - `Docker: twitch-drops-manager-api-1`
  - `Docker: twitch-drops-manager-worker-1`
  - `Docker: twitch-drops-manager-frontend-1`
- `/health` stays public, so Uptime Kuma needs no session. Do not probe personal
  endpoints without a session.

## Logs / diagnostics

```bash
docker ps --filter name=twitch-drops-manager
docker logs --tail 200 twitch-drops-manager-api-1
docker logs --tail 200 twitch-drops-manager-worker-1
docker logs --tail 100 twitch-drops-manager-frontend-1
```

`httpx`/`httpcore` request logging is disabled below WARNING, so tokens should
not appear in logs. Telegram errors are redacted. Rotate the Telegram token if an
older log ever exposed it.

## Rate limits / external quotas

| Provider | Limit / behavior |
|---|---|
| Sunkwi catalog | ~1 request / 300s; cached in memory + `/data/sunkwi_cache.json`, honors reset headers, serves stale during 429/5xx |
| Twitch Helix | app token; normal Helix limits (shared scan) |
| Twitch GQL | internal API; one call per active user per progress run; profile cached/persisted per user |
| Telegram | Bot API; per-user digests, atomically deduped |
| Auth | `AUTH_RATE_LIMIT_PER_MINUTE` per client IP per minute (`429`) |

The worker cadence (scan 15m, per-user progress 5m, watcher 1m) stays below the
catalog window. Runtime grows with the number of active users; the practical
ceiling on the Pi is dozens.

## Backups

Back up the SQLite database (consistent copy via the SQLite backup API):

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
backup; keep a copy of the current file first. See
[DATA_MODEL.md](DATA_MODEL.md).

Back up **before** the multi-user upgrade and keep that copy until the soak
period ends; it is the only way to roll back while keeping post-upgrade data.

## Rollback

- **Code rollback:** redeploy the previous commit through Portainer.
- **Data:** the previous release reads/writes the frozen legacy tables, so it
  will not see data written after migration. To roll back and keep post-upgrade
  data, restore the pre-upgrade backup (stop the stack first).
- New tables are additive; an older release ignores them. Do not drop legacy
  tables or downgrade the schema without a backup.

After rollback, the app returns to the single-user flow and the old
`API_TOKEN` behavior; re-add `API_TOKEN` to the stack env only for that old
release.

## Security

- Twitch OAuth tokens are stored **plaintext** in SQLite. Protect the volume and
  host access; do not share the DB file.
- Session cookies are the browser auth: `HttpOnly` session + CSRF header. There
  is no API token in the frontend bundle.
- Set `PUBLIC_ORIGIN` and `ALLOWED_HOSTS` in production; keep
  `SESSION_COOKIE_SECURE=auto` (or `true`) on HTTPS.
- Keep `REGISTRATION_OPEN=false` and a long random `REGISTRATION_CODE`; clear the
  code to close registration.
- Never commit `.env`/`.env.save`; use `.env.example`.
- Rotate the Telegram bot token if it appears in logs, and rotate the invite code
  if it leaks.
- Revoke the Twitch app authorization at Twitch → Settings → Connections if
  needed; then reconnect in the app.
- Read-only boundary: the app never claims drops or automates watching. The
  focused watcher is a queue focus pointer only.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Startup stops with a migration/owner error | legacy `twitch_auth.user_id` empty or conflicting user | Set `OWNER_TWITCH_ID` or fix the legacy row, then restart; restore backup if needed |
| `/auth/me` returns 401 after login | cookie not stored, expired session, or disabled user | Check cookie `Secure`/domain and `SESSION_COOKIE_SECURE`; sign in again; check admin active state |
| `403` on a mutation | missing/mismatched `X-CSRF-Token`, or non-admin scan | Ensure the client echoes `tdm_csrf`; use an admin for scans |
| `403` registration closed | empty `REGISTRATION_CODE`, `REGISTRATION_OPEN=false` | Set a code or open registration intentionally |
| `409` connecting Twitch | a different Twitch account is already signed in | Sign out, then connect |
| `429` on login | auth rate limit | Wait a minute; raise `AUTH_RATE_LIMIT_PER_MINUTE` only if appropriate |
| Public cookie is not `Secure` | forwarded scheme not preserved, or Funnel changed | Check nginx `X-Forwarded-Proto` map/Funnel; set `SESSION_COOKIE_SECURE=true` if needed |
| One user's progress stops | expired/invalid user token | Profile shows reconnect; the worker skips only that user |
| `429 Too Many Requests` from `drops.sunkwi.com` | catalog limit (1/300s) | Cache should serve stale; wait for reset; cold cache can fail |
| Telegram messages missing for one user | no chat id or opt-out | Settings → Telegram; send test; check worker logs |
| Duplicate Telegram messages | older build before atomic per-user dedupe | Deploy current release |
| SQLite `database is locked` | long write / snapshot | Retry; keep writes short; check worker logs |
| `no such column` after deploy | model column added without migration | Use a side table / explicit migration; see DATA_MODEL |

## Retention

- Progress snapshots: 24h per user.
- Streams/matches: replaced each scan (shared).
- Drop progress: replaced each per-user sync.
- Campaigns: stale rows deleted on scan.
- Sessions: expired rows pruned at startup and during the scan.
- Notifications/campaign starts: retained/pruned as in [DATA_MODEL.md](DATA_MODEL.md).
