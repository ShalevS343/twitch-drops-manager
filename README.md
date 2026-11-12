# Twitch Drops Manager

A self-hosted dashboard for Twitch Drops: track campaigns, discover eligible live
streams, follow your personal drop progress, and get Telegram alerts when a drop
is ready to claim. A small group can share one deployment: each person signs in
with their own Twitch account and sees only their own progress, games, focus
target, and Telegram destination.

The app is **read-only** with respect to Twitch rewards: it never claims drops and
never automates watching.

## Features

- **Multi-user by Twitch login** — no passwords or email accounts. The first
  admin needs a matching `OWNER_TWITCH_ID`, a valid invite code
  (`REGISTRATION_CODE`), or explicit `REGISTRATION_OPEN=true`; friends join with
  the invite code. Personal data is isolated per user; the campaign catalog and
  live streams are shared and scanned once.
- **Campaign catalog** — active/upcoming campaigns, rewards, requirements, and end
  dates from the public Drops API.
- **Live stream discovery** — Drops-enabled streams for your selected games via
  Twitch Helix.
- **Personal progress** — read-only Twitch inventory via your own Twitch login:
  minutes watched, percentages, remaining time, and claimed state.
- **Watch queue** — live streams matched to your in-progress campaigns, ordered by
  urgency.
- **Per-user Telegram alerts** — ready-to-claim drops, campaign deadline reminders
  (24h/2h), campaign starts for tracked games (including games with no current
  campaign), focused-live offline alerts, and focused campaign-completion alerts,
  each to your own chat id. Connect from Settings → Telegram → Connect Telegram;
  the chat id is read-only. New live streams are not sent to Telegram.
- **Track any game** — add a game by name in Settings even if it is not in the
  catalog; get notified when its next campaign becomes active.
- **Start watching** — opens the real Twitch stream and focuses your watcher on
  that streamer/campaign. No local timer or elapsed-time tracking.
- **Focused watcher** — keep one live target selected from your watch queue for
  the most urgent campaign, switch it manually or with **Next live**, get a
  Telegram alert if that live goes offline while the campaign is open, and turn
  focus off automatically when the campaign completes. One watcher per user.
- **Admin controls** — admins list/enable/disable users and run the global scan;
  non-admins cannot trigger scans or manage users.
- **Top 5 per game** — watch queue and live streams group by game and show the
  top 5 by default, with a 5/10/20/All selector.
- **Completed campaigns** — campaigns with every drop claimed are tagged
  **Completed**, use a green border, and sort after unfinished campaigns.
- **Tabbed dashboard** — Overview, Campaigns, Progress, Watch queue, Streams,
  Settings, and a profile page. High-contrast violet design, responsive.
- **Rate-limit resilient** — the public catalog is cached to disk and served during
  the provider's 1-request/300s window.

## Architecture

```
Twitch Helix ─┐
Sunkwi Drops ─┼─> worker (APScheduler) ──> SQLite (/data/drops.db)
Twitch GQL ───┘                                   │
                                                  ├─> FastAPI /api/v1 ─> nginx ─> React UI
Telegram Bot <────────────────────────────────────┘
```

- `backend/` — FastAPI API + APScheduler worker, async SQLAlchemy, SQLite.
- `frontend/` — React 18 + TypeScript + Vite + TanStack Query, served by nginx.
- `infra/docker-compose.yml` — api, worker, frontend, shared `drops_data` volume.
- Optional monitoring: Kuma labels consumed by the local `kuma-sync` container.

## Quick start

```bash
cp .env.example .env
# fill in TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET
# optional: TELEGRAM_BOT_TOKEN, REGISTRATION_CODE, OWNER_TWITCH_ID,
#           PUBLIC_ORIGIN, ALLOWED_HOSTS

docker compose --project-directory infra -f infra/docker-compose.yml up -d --build
```

- UI (local): `http://localhost:8282` (Compose binds loopback)
- Public deployment: `https://pi.taile9ec1c.ts.net` via Tailscale Funnel
- API docs (local backend): `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health`

Progress requires each person to sign in with Twitch once: approve the authorize
page, then paste the resulting `https://www.twitch.tv/#access_token=...` URL back
into the app. The token is stored server-side for that user's account; there are
no passwords. The first admin needs `OWNER_TWITCH_ID`, a valid
`REGISTRATION_CODE`, or `REGISTRATION_OPEN=true`. Later users need the invite code
unless registration is explicitly open. Each user connects Telegram from
Settings → Telegram → Connect Telegram; the chat id is read-only.

There is no shared nginx basic-auth password. The public site is gated by Twitch
login plus the invite code, and the frontend binds loopback so it is reached
through the public HTTPS URL. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Documentation

Start with [`docs/README.md`](docs/README.md). Key references:

- [Architecture](docs/ARCHITECTURE.md)
- [Backend](docs/BACKEND.md)
- [API](docs/API.md)
- [Data model](docs/DATA_MODEL.md)
- [Frontend](docs/FRONTEND.md)
- [Operations & deployment](docs/OPERATIONS.md)
- [Development](docs/DEVELOPMENT.md)
- [Performance audit](docs/backend-performance.md)
- [Changelog](docs/CHANGELOG.md)
- [Current status / handoff](docs/STATUS.md)
- [Architecture decisions](docs/DECISIONS.md)

## Security

- `.env`, `.env.save`, and other `.env.*` backups are **not** versioned. Set
  `chmod 600 .env`; never commit tokens.
- Twitch OAuth tokens are stored in SQLite (`twitch_accounts`) and the app can
  read each user's drops inventory. Protect the Docker volume and host access.
- Browser auth is an `HttpOnly` session cookie plus a CSRF header; there is no
  API token in the frontend bundle. `SESSION_COOKIE_SECURE=true` is the Compose
  default. Use `PUBLIC_ORIGIN` and `ALLOWED_HOSTS`; registration is invite-only by
  default and a fresh DB is not implicitly open.
- The frontend publishes only on `127.0.0.1:8282`; nginx adds CSP, HSTS,
  nosniff, frame-deny, referrer and permissions headers.
- Each user can only read their own personal data; admins see safe account
  metadata only (never tokens or chat ids).
- Auth and per-user actions are rate-limited. Rotate the Twitch client secret if
  a token request ever failed on an old build, and rotate the Telegram bot token
  if it was ever written to logs.
- The app never claims rewards and never automates viewing; see
  [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Repository layout

```
backend/
  app/
    api/v1/        HTTP endpoints
    core/          settings, DB, logging, security
    domain/        SQLAlchemy models, schemas, parsing
    providers/     Sunkwi, Twitch Helix, Twitch user/GQL, Telegram
    repositories/  query layer
    services/      scan, progress, metrics, factories
    worker/        APScheduler runner
  tests/
frontend/
  src/
    api/           fetch client + TypeScript contracts
    components/    shared + UI primitives
    hooks/         react-query hooks, tab routing
    pages/         one component per tab
    lib/           formatting, tab metadata
infra/
  docker-compose.yml
docs/
```

## License / usage

Private project. Twitch, Drops, and related marks belong to Twitch Interactive.
