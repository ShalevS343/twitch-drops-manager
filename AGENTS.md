# AGENTS.md — working agreement for this repository

This file is the entry point for every AI/coding session working on the Twitch
Drops Manager. Read it before changing code.

## 1. Start every session here

1. Read [`docs/STATUS.md`](docs/STATUS.md) — current state, pending work, known
   issues.
2. Read [`docs/README.md`](docs/README.md) — documentation map.
3. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the big picture.
4. Run `git status -sb` and `git log --oneline -5`.
5. Check the live state if the task touches deployment: `docker ps`, Portainer
   stack `twitch-drops-manager`.

## 2. Documentation is part of "done"

**Every session that changes behavior, APIs, schema, environment variables,
deployment, or UI must update the docs before finishing.**

Required updates:

| Change | Update |
|---|---|
| Any change | `docs/STATUS.md` (current state + pending items) |
| Any user-visible change | `docs/CHANGELOG.md` (dated entry) |
| Endpoint / contract | `docs/API.md` and `frontend/src/api/types.ts` |
| Model / table / index | `docs/DATA_MODEL.md` |
| Env var / compose / deploy | `docs/OPERATIONS.md` and `.env.example` |
| Backend module/provider/service | `docs/BACKEND.md` |
| Frontend page/component/design | `docs/FRONTEND.md` |
| Performance change | `docs/backend-performance.md` (or link a new report) |
| Architectural decision | `docs/DECISIONS.md` (new ADR) |

- Use ISO dates (`YYYY-MM-DD`) in the changelog.
- Mark planned work as **planned**; do not describe it as shipped.
- If a change genuinely needs no doc update, say why in the final response.
- Keep `docs/STATUS.md` short and current: it is the handoff between sessions.

## 3. Product and safety rules

- **No local user/account system**: the Twitch profile is read from Twitch and
  only the OAuth token/profile cache is persisted.
- **Secrets**: never read, print, commit, or copy `.env` / `.env.save`. Never
  log tokens. Use `.env.example` for documentation.
- **No live deployment** (Portainer redeploy, `docker compose up`, container
  recreation) without explicit user instruction.
- Do not delete user data (Docker volumes, SQLite DB) without explicit
  confirmation and a backup.
- The app is single-user and runs on a Raspberry Pi; prefer simple, reversible
  changes over distributed-systems complexity.

## 4. Development commands

Backend:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
PYTHONPATH=$PWD pytest -q
ruff check app tests
```

Frontend:

```bash
cd frontend
npm install
npm run build       # tsc --noEmit && vite build
npm run dev         # Vite on :5173, proxies /api to :8000
```

Docker:

```bash
docker compose --project-directory infra -f infra/docker-compose.yml config -q
docker compose --project-directory infra -f infra/docker-compose.yml up -d --build
```

Expected current baseline: backend tests **71 passed**, ruff clean, frontend build
passes.

## 5. Worktree workflow for parallel work

Use separate git worktrees per independent lane (backend, frontend, infra, QA) to
avoid cross-contamination. From the main worktree:

```bash
git worktree add /tmp/tdm-backend -b feat/my-backend
git worktree add /tmp/tdm-frontend -b feat/my-frontend
```

- Work only inside your assigned worktree.
- Commit on your branch; do not push or merge unless asked.
- Merge into an integration branch, run the full suite, then merge to `main`.
- Keep backend and frontend lanes on disjoint file sets when parallelizing.

## 6. Code conventions

- Backend: FastAPI + async SQLAlchemy; keep query logic in `repositories/`,
  orchestration in `services/`, contracts in `domain/schemas.py`. Additive API
  changes only unless a breaking change is explicitly approved.
- Avoid hidden `selectin` loading for read paths; use explicit `load_only`/flat
  joins when the endpoint only needs a few columns (see the performance report).
- Frontend: React + TypeScript strict, no new dependencies without need; all
  server calls go through `src/api/client.ts`; data via TanStack Query hooks.
- Use the design tokens in `src/index.css`; do not introduce gradients, glows,
  pill shapes, or a generic icon set.
- Keep `Fake`/test patterns in `backend/tests`.

## 7. Definition of done

- [ ] Behavior implemented and manually sanity-checked.
- [ ] `PYTHONPATH=$PWD pytest -q` passes (backend changes).
- [ ] `ruff check app tests` passes (backend changes).
- [ ] `npm run build` passes (frontend changes).
- [ ] API contract matches `frontend/src/api/types.ts`.
- [ ] Docs updated per section 2.
- [ ] `docs/STATUS.md` reflects the new current state and pending items.
- [ ] No secrets, `.env`, or unrelated files in the diff.
