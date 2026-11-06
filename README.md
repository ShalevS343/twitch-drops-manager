# Twitch Drops Manager

A self-hosted dashboard for Twitch Drops: track campaigns, discover eligible live
streams, follow your personal drop progress, and get Telegram alerts when a drop
is ready to claim.

The app is **read-only** with respect to Twitch rewards: it never claims drops and
never automates watching.

## Features

- **Campaign catalog** — active/upcoming campaigns, rewards, requirements, and end
  dates from the public Drops API.
- **Live stream discovery** — Drops-enabled streams for your selected games via
  Twitch Helix.
- **Personal progress** — read-only Twitch inventory via a user login: minutes
  watched, percentages, claimed state, ETA from recent watch rate.
- **Watch queue** — live streams matched to your in-progress campaigns, ordered by
  urgency.
- **Telegram alerts** — one digest per run, atomic dedupe: ready-to-claim drops,
  campaign deadline reminders (24h/2h), newly eligible streams, and campaign
  starts for tracked games (including games with no current campaign).
- **Track any game** — add a game by name in Settings even if it is not in the
  catalog; get notified when its next campaign becomes active.
- **Manual watch sessions** — start one campaign at a time, open the real stream,
  and track elapsed time locally. The timer never controls playback or simulates
  viewing.
- **Top 5 per game** — watch queue and live streams group by game and show the
  top 5 by default, with a 5/10/20/All selector.
- **Tabbed dashboard** — Overview, Campaigns, Progress, Watch queue, Streams,
  Settings, and a Twitch profile page. High-contrast violet design, responsive.
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
# and TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (optional)

docker compose --project-directory infra -f infra/docker-compose.yml up -d --build
```

- UI: http://localhost:8282
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

Twitch progress requires one manual authorization: **Profile → Connect Twitch**,
approve, then paste the resulting `https://www.twitch.tv/#access_token=...` URL
back into the app. The token is stored server-side; there are no local user
accounts.

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

- `.env` and `.env.save` are **not** versioned. Never commit tokens.
- Twitch OAuth tokens are stored in SQLite (`twitch_auth`) and the app can read
  your drops inventory. Protect the Docker volume and host access.
- Set `API_TOKEN` to require `X-API-Token` on mutating API endpoints.
- Rotate the Telegram bot token if it was ever written to logs.
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
