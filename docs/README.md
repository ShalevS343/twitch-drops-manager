# Documentation

This is the source of truth for how the service works and how to operate it.
Every session is expected to keep it current (see the contract below).

## Read in this order

1. [`STATUS.md`](STATUS.md) — current state, live deployment, pending work, known issues.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md) — components, data flows, boundaries.
3. [`BACKEND.md`](BACKEND.md) — services, providers, repositories, worker.
4. [`API.md`](API.md) — endpoint reference and contracts.
5. [`DATA_MODEL.md`](DATA_MODEL.md) — tables, relationships, indexes, retention.
6. [`FRONTEND.md`](FRONTEND.md) — tabs, pages, hooks, design system.
7. [`OPERATIONS.md`](OPERATIONS.md) — deployment, env vars, monitoring, backups, troubleshooting.
8. [`DEVELOPMENT.md`](DEVELOPMENT.md) — local setup, tests, worktree workflow.
9. [`backend-performance.md`](backend-performance.md) — measured performance audit + P0 results.
10. [`CHANGELOG.md`](CHANGELOG.md) — dated history.
11. [`DECISIONS.md`](DECISIONS.md) — architecture decision records.

Repository-level instructions for agents: [`../AGENTS.md`](../AGENTS.md).

## Documentation contract

Any change to behavior, APIs, schema, env vars, deployment, or UI must update the
docs **before the session ends**:

| Change | Required doc |
|---|---|
| Any change | [`STATUS.md`](STATUS.md) |
| User-visible change | [`CHANGELOG.md`](CHANGELOG.md) |
| Endpoint / request / response | [`API.md`](API.md) + `frontend/src/api/types.ts` |
| Table / column / index | [`DATA_MODEL.md`](DATA_MODEL.md) |
| Env var / compose / deploy | [`OPERATIONS.md`](OPERATIONS.md) + `.env.example` |
| Backend module/provider/service | [`BACKEND.md`](BACKEND.md) |
| Frontend page/component/design | [`FRONTEND.md`](FRONTEND.md) |
| Performance | [`backend-performance.md`](backend-performance.md) |
| Architectural decision | [`DECISIONS.md`](DECISIONS.md) |

Rules:

- Use ISO dates.
- Mark planned work as **planned**, not shipped.
- Keep `STATUS.md` concise; it is the handoff.
- Never put secrets in docs. Use placeholders like `<token>`.
- If no doc update is needed, state why in the final response.

## What lives where

- **Architecture** — the shape of the system and why.
- **Backend/API/Data** — implementation and contracts.
- **Frontend** — UI structure, data fetching, design system.
- **Operations** — how to run, deploy, monitor, recover.
- **Development** — how to change code safely.
- **Status/Changelog/Decisions** — what is true now and why we chose it.

## Last updated

2026-11-12 — multi-user accounts, auth, and deployment docs.
