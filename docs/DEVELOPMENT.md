# Development

## Prerequisites

- Python 3.10+ (container uses 3.12)
- Node.js 20+ and npm
- Docker + Docker Compose (for the full stack)
- A Twitch app (client id/secret) for stream discovery; a Telegram bot is optional

## Repository

```
backend/     FastAPI + async SQLAlchemy + APScheduler worker
frontend/    React + TypeScript + Vite + TanStack Query
infra/       Docker Compose
docs/        This documentation set
```

Read [`../AGENTS.md`](../AGENTS.md) and [`STATUS.md`](STATUS.md) before working.

## Backend setup

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

# Tests + lint
PYTHONPATH=$PWD pytest -q
ruff check app tests

# Run the API locally (SQLite under backend/data by default)
uvicorn app.main:app --reload --port 8000
# Optional: run the worker
python -m app.worker.scheduler
```

Configuration comes from `.env`/`../.env` via pydantic-settings. For local work,
a `.env` with `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and optional Telegram
values is enough. `DATABASE_URL` defaults to `sqlite+aiosqlite:///./data/drops.db`;
the API creates the directory and tables.

Tests use in-memory SQLite with `StaticPool`; no live providers are called in the
suite.

## Frontend setup

```bash
cd frontend
npm install
npm run dev      # Vite :5173, /api proxy -> localhost:8000
npm run build    # tsc --noEmit && vite build
npm run typecheck
```

The Vite dev server proxies `/api` to `http://localhost:8000`. For a different API,
set `VITE_API_BASE_URL` (and `VITE_API_TOKEN` if `API_TOKEN` is set) at build time.

## Docker

```bash
# validate compose interpolation
docker compose --project-directory infra -f infra/docker-compose.yml config -q

# build + run the stack
docker compose --project-directory infra -f infra/docker-compose.yml up -d --build
```

Ports: API `8000`, UI `8282`. The `drops_data` volume is shared by api/worker.

## Worktree workflow

Parallel work uses git worktrees so backend/frontend/infra lanes do not share a
working tree:

```bash
git worktree add /tmp/tdm-backend -b feat/my-backend
git worktree add /tmp/tdm-frontend -b feat/my-frontend
# in each worktree: implement, test, commit on its branch

# integration
git worktree add /tmp/tdm-integration -b feat/integration
cd /tmp/tdm-integration
git merge --no-ff feat/my-backend
git merge --no-ff feat/my-frontend
cd backend && PYTHONPATH=$PWD pytest -q
cd ../frontend && npm run build
```

- Keep the main `/opt/twitch-drops-manager/twitch-drops-manager` checkout on
  `main`.
- Backend and frontend lanes should own disjoint files when run in parallel.
- Do not push/merge/deploy without explicit instruction.
- Worktrees under `/home/server/.local/share/opencode/worktree/...` are managed by
  the OpenCode tool; plain `git worktree add /tmp/...` is fine too.

## Code conventions

- Backend: async SQLAlchemy; query logic in `repositories/`, orchestration in
  `services/`, contracts in `domain/schemas.py`. Additive API changes.
- Read paths: avoid hidden `selectin` graphs; use explicit `load_only`/flat joins
  (see [`backend-performance.md`](backend-performance.md)).
- Frontend: TypeScript strict (`noUnusedLocals`), no router dependency, all server
  calls via `api/client.ts`, data via hooks.
- Design: use tokens in `frontend/src/index.css`; no gradients, glows, backdrop
  blur, pill components, or generic outline icons.
- Secrets: never read/print/commit `.env` or `.env.save`.
- Tests: extend existing patterns; keep deterministic (no date-dependent fixtures).

## Adding a feature

1. Backend model/schema/repository/service/endpoint as needed.
2. Frontend type + client + hook + page/component.
3. Tests: backend behavior; frontend build/typecheck.
4. Docs: [API](API.md), [DATA_MODEL](DATA_MODEL.md), [BACKEND](BACKEND.md),
   [FRONTEND](FRONTEND.md), [STATUS](STATUS.md), [CHANGELOG](CHANGELOG.md).
5. Run the full suite and build.

## Commit / branch style

- Imperative, scoped subjects: `perf(backend): ...`, `feat(ui): ...`,
  `fix(twitch): ...`, `docs: ...`.
- Keep merge commits for feature branches (`--no-ff`).
- Do not commit `dist/`, `node_modules/`, `.env`, or secrets.

## Definition of done

See [`../AGENTS.md`](../AGENTS.md) section 7. In short: behavior verified, tests
pass, lint/build pass, contracts aligned, docs updated, no secrets.

## Current baseline

- Backend tests: **58 passed**
- Ruff: clean
- Frontend: `npm run build` passes
- Main includes P0 performance work, game tracking/campaign-start alerts, and the
  violet high-contrast UI
