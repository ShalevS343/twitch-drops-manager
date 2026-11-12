# Multi-user Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Twitch-as-login, local users, per-user data isolation, optional per-user Telegram, safe migration, and staged removal of shared basic auth.

**Architecture:** Twitch validates identity; the backend stores a `users` row keyed by Twitch user id, an opaque server session, and per-user personal tables. Shared catalog/stream tables remain global and are scanned once. Progress and watcher jobs loop per active user with isolated sessions.

**Tech Stack:** FastAPI, async SQLAlchemy + aiosqlite, APScheduler, React 18 + TypeScript + TanStack Query, Docker Compose/nginx.

**Spec:** `docs/superpowers/specs/2026-11-12-multi-user-accounts-design.md`

> **Post-approval update:** nginx basic auth was removed from the branch. The
> public UI is gated by Twitch sign-in + invite code; personal API endpoints
> require a session. The staged-removal steps below are historical.

## Global Constraints

- No new runtime dependencies. No Alembic; new tables are created with `create_all` and data is migrated by a one-transaction helper.
- App remains read-only toward Twitch rewards; never claim or automate watching.
- SQLite is the only database in this phase; keep one writer and sequential worker loops.
- Never log tokens, `.env`, or secrets. Telegram errors must be redacted.
- Do not deploy, push, or merge to `main` without explicit instruction.
- Every behavior change updates the docs required by `AGENTS.md`.
- Backend gate: `cd backend && PYTHONPATH=$PWD pytest -q && ruff check app tests`.
- Frontend gate: `cd frontend && npm run build`.
- Deploy remains staged: basic auth stays until app auth is verified.

## Review Focus

1. **Cross-user leakage:** any personal endpoint, repository, worker path, or cached frontend query returning another user's data. Tests must cover two users on every personal endpoint.
2. **Expired/invalid Twitch token recovery:** `reconnect_required` must set only on user-token failures and clear on reconnect/sync.
3. **Migration on a live legacy DB:** partial failure, rerun, and concurrent API+worker startup must not corrupt or misassign data.
4. **Shared-browser user switching:** logout/login must clear query caches and in-flight requests; CSRF must block forged writes.
5. **Telegram opt-in/out and redaction:** opted-out users get no backlog; provider errors never expose the bot token.

---

### Task 1: Add the new data model, settings, and migration

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/db.py`
- Create: `backend/app/core/migrations.py`
- Test: `backend/tests/test_models.py`, create `backend/tests/test_migration.py`

**Interfaces:**
- Produces model classes: `User`, `UserSession`, `TwitchAccount`, `UserGame`, `UserDropProgress`, `UserProgressSnapshot`, `UserCampaignCompletion`, `UserWatchFocus`, `UserNotification`, `UserCampaignStart`, `AppMeta`.
- Produces `async def run_multi_user_migration(connection) -> None`.
- Produces settings: `registration_code`, `registration_open`, `owner_twitch_id`, `session_ttl_days`, `session_cookie_secure`, `public_origin`, `allowed_hosts`, `auth_rate_limit_per_minute`.
- `User.twitch_user_id` is non-empty unique; `TwitchAccount.user_id` is unique and does not duplicate `twitch_user_id`.

- [ ] **Step 1: Write failing model tests**

Assert: `User.__table__.c.twitch_user_id.unique`; `UserSession.__table__.c.token_hash.unique`; `UserGame` has `UniqueConstraint("user_id","game_id")`; `UserDropProgress` unique `(user_id, drop_id)`; `UserNotification` unique `(user_id, dedupe_key)`; `UserWatchFocus` has no `id=1` check.

- [ ] **Step 2: Run the model tests**

Run: `cd backend && PYTHONPATH=$PWD pytest tests/test_models.py -q`
Expected: FAIL with missing classes.

- [ ] **Step 3: Implement the models and settings**

Use the spec's column ownership rules. Keep global `Game`, `Campaign`, `Reward`, `Stream`, `StreamCampaignMatch`, `ScanRun` unchanged. **Keep the old `TwitchAuth`, `TwitchProfile`, `WatchFocus`, `DropProgress`, `ProgressSnapshot`, `CampaignCompletion`, `Notification`, `CampaignStart` classes in place for now** so existing code/tests keep running; add the new `User*` models alongside them. The migration reads the legacy tables by name. Remove the old classes only in Task 6 after every caller is scoped.

- [ ] **Step 4: Write failing migration tests**

Use an in-memory SQLite engine. Create legacy tables with raw SQL (`twitch_auth`, `twitch_profile`, `drop_progress`, `progress_snapshots`, `campaign_completions`, `watch_focus`, `notifications`, `campaign_starts`, `games`), seed one owner, call `run_multi_user_migration(connection)` twice, and assert one owner, copied rows, `app_meta['multi_user_v1']='done'`, and no duplicate rows. Add tests for: no legacy token, empty legacy `user_id` raises, expired token sets `reconnect_required`, conflicting `users` row raises.

- [ ] **Step 5: Run the migration tests**

Expected: FAIL with `ImportError`/missing helper.

- [ ] **Step 6: Implement `run_multi_user_migration`**

Run inside the transaction opened by `init_db()` after `create_all`. Claim `app_meta['multi_user_v1']` with `INSERT OR IGNORE`; if already present, return. Use `INSERT OR IGNORE`/upserts for every copy. Abort with `RuntimeError` on empty/mismatched legacy owner. Set `reconnect_required` when the legacy expiry is past. Seed Telegram from `TELEGRAM_CHAT_ID`. Create a placeholder admin when `OWNER_TWITCH_ID` is set and there is no legacy token. Call the helper from `init_db()` inside the same `engine.begin()` block that runs `create_all`.

- [ ] **Step 7: Verify**

Run: `cd backend && PYTHONPATH=$PWD pytest tests/test_models.py tests/test_migration.py -q && ruff check app tests`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/domain/models.py backend/app/core/config.py backend/app/core/db.py backend/app/core/migrations.py backend/tests/test_models.py backend/tests/test_migration.py
git commit -m "feat(backend): add multi-user schema and migration"
```

---

### Task 2: Add auth repositories, session/CSRF security, and auth service

**Files:**
- Create: `backend/app/repositories/users.py`, `user_sessions.py`, `twitch_accounts.py`, `user_games.py`
- Create: `backend/app/core/security.py` (replace current API-token helper)
- Create: `backend/app/core/rate_limit.py`
- Create: `backend/app/core/middleware.py`
- Create: `backend/app/services/auth_service.py`
- Modify: `backend/app/core/exceptions.py`, `backend/app/domain/schemas.py`, `backend/app/api/deps.py`
- Test: create `backend/tests/test_auth.py`, `backend/tests/test_rate_limit.py`

**Interfaces:**
- `UserRepository`, `UserSessionRepository`, `TwitchAccountRepository`, `UserGameRepository` with the methods listed in the spec/tasks.
- `new_opaque_token() -> str`, `hash_token(token: str) -> str`, `create_auth_session(session, user_id, ttl_days) -> tuple[str, str, UserSession]`, `set_auth_cookies(response, request, session_token, csrf_token, max_age)`, `clear_auth_cookies(response)`.
- `get_current_user(request, session) -> User`, `get_optional_user(request, session) -> User | None`, `require_admin(user) -> User`.
- `AuthService.connect(redirect_url, invite_code, current_user) -> AuthResult`, `logout(raw_token)`, `disconnect(user_id)`, `update_telegram(user_id, chat_id, enabled)`, `registration_state()`.
- `ReconnectRequiredError` distinct from `NotConfiguredError`.

- [ ] **Step 1: Write failing auth tests**

Cover: first user becomes admin; second user requires a valid code; empty code + `REGISTRATION_OPEN=false` -> 403; explicit open works; existing user logs in; inactive user 403; different Twitch id while signed in -> 409; missing `user_id`/`login` -> 400; `secrets.compare_digest` path; session hash stored; expired session rejected; CSRF mismatch rejected; disabled user rejected.

- [ ] **Step 2: Run tests**

Expected: FAIL with missing modules/functions.

- [ ] **Step 3: Implement repositories and auth service**

Use the spec's registration table. Fetch profile after validation; on provider failure keep `login` as display name. Save token with `expires_at`, `reconnect_required=False`, `last_error=""`. Clear pending start rows when Telegram is disabled. `disconnect` deletes the account and that user's personal rows but keeps the user.

- [ ] **Step 4: Implement session/CSRF middleware**

`CSRFMiddleware`: for `/api/v1/*` unsafe methods, skip `/api/v1/auth/twitch/connect`; if the session cookie exists, require `tdm_csrf` and `X-CSRF-Token` to match via `compare_digest`. `NoStoreMiddleware`: add `Cache-Control: no-store` to authenticated API responses. Add `TrustedHostMiddleware` when `allowed_hosts` is set.

- [ ] **Step 5: Implement rate limiting**

Sliding-window limiter keyed by client IP (first `X-Forwarded-For` value, else `request.client.host`). Expose `check(key) -> bool` and `retry_after(key) -> int`; use `auth_rate_limit_per_minute`.

- [ ] **Step 6: Verify**

Run: `cd backend && PYTHONPATH=$PWD pytest tests/test_auth.py tests/test_rate_limit.py -q && ruff check app tests`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/repositories/users.py backend/app/repositories/user_sessions.py backend/app/repositories/twitch_accounts.py backend/app/repositories/user_games.py backend/app/core/security.py backend/app/core/rate_limit.py backend/app/core/middleware.py backend/app/services/auth_service.py backend/app/core/exceptions.py backend/app/domain/schemas.py backend/app/api/deps.py backend/tests/test_auth.py backend/tests/test_rate_limit.py
git commit -m "feat(backend): add users, sessions, CSRF, and auth service"
```

---

### Task 3: Add auth/admin API endpoints and wire middleware

**Files:**
- Create: `backend/app/api/v1/auth.py`, `backend/app/api/v1/admin.py`
- Modify: `backend/app/api/v1/router.py`, `backend/app/main.py`, `backend/app/domain/schemas.py`
- Test: `backend/tests/test_auth_api.py`, `backend/tests/test_admin_api.py`

**Interfaces:**
- Endpoints from the spec: `GET /auth/me`, `GET /auth/twitch/authorize`, `POST /auth/twitch/connect`, `POST /auth/logout`, `PATCH /auth/me`, `POST /auth/twitch/disconnect`, `GET /admin/users`, `PATCH /admin/users/{id}`.
- `AuthMeOut`, `AuthUserOut`, `RegistrationStateOut`, `AuthConnectIn`, `AuthConnectOut`, `TelegramSettingsIn`, `AdminUserOut`, `AdminUserUpdate`.

- [ ] **Step 1: Write failing API tests**

Use `httpx.AsyncClient` with `ASGITransport` or direct route calls. Cover: unauthenticated `/auth/me`; first connect sets both cookies; public connect with bad code -> 403; rate limit -> 429; logout clears cookies and session; PATCH Telegram only affects current user; disconnect clears that user only; non-admin gets 403 on admin routes; admin cannot self-disable; disabling revokes sessions.

- [ ] **Step 2: Run tests**

Expected: FAIL with 404/missing router.

- [ ] **Step 3: Implement auth and admin routers**

Set cookies on connect. Trigger the first progress sync only after the session is committed, and never on a failed registration. Include `registration_open`/`invite_required` in `/auth/me`. Admin list must never expose tokens or chat ids.

- [ ] **Step 4: Wire routers and middleware**

Add both routers. Add CSRF/no-store/trusted-host middleware. Keep `/health` public.

- [ ] **Step 5: Verify**

Run: `cd backend && PYTHONPATH=$PWD pytest tests/test_auth_api.py tests/test_admin_api.py -q && ruff check app tests`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/auth.py backend/app/api/v1/admin.py backend/app/api/v1/router.py backend/app/main.py backend/app/domain/schemas.py backend/tests/test_auth_api.py backend/tests/test_admin_api.py
git commit -m "feat(api): add auth and admin endpoints"
```

---

### Task 4: Make personal repositories and services user-scoped

**Files:**
- Modify: `backend/app/repositories/progress.py`, `campaign_completions.py`, `notifications.py`, `campaign_starts.py`, `watch_focus.py`
- Modify: `backend/app/services/progress_service.py`, `watch_focus_service.py`, `watch_queue_service.py`, `factory.py`
- Create: `backend/app/services/profile_service.py`
- Test: update `backend/tests/test_progress_service.py`, `test_notifications.py`, `test_watch_focus.py`, `test_watch_queue.py`

**Interfaces:**
- `ProgressRepository(session, user_id)`, `CampaignCompletionRepository(session, user_id)`, `NotificationRepository(session, user_id)`, `CampaignStartRepository(session, user_id)`, `WatchFocusRepository(session, user_id)`.
- `ProgressService(session, user_id, settings, provider, telegram).run()`.
- `WatchFocusService(session, user_id, telegram).reconcile()` and existing dispatch methods.
- `build_watch_queue(session, user_id)`.
- `ProfileService.refresh(user_id, provider=None, session_factory=None)`, `schedule(user_id)`, `warm_up(session_factory=None)`, `shutdown()`.

- [ ] **Step 1: Write failing isolation tests**

Two users with different progress/completions/focus/notifications must not see each other's rows. Expired token sets `reconnect_required`; successful sync clears it; global client error does not set it. Telegram disabled means no send and pending start rows deleted.

- [ ] **Step 2: Run tests**

Expected: FAIL on singleton/missing `user_id` signatures.

- [ ] **Step 3: Implement scoped repositories and services**

Use the new `User*` tables. `ProgressService` skips users already `reconnect_required`. `ProfileService` replaces the singleton warm-up and saves profile fields on `users`.

- [ ] **Step 4: Update factories**

`build_progress_service(session, user_id)`, `build_watch_focus_service(session, user_id)`, `build_scan_service(session)`, `build_auth_service(session)`.

- [ ] **Step 5: Verify**

Run: `cd backend && PYTHONPATH=$PWD pytest tests/test_progress_service.py tests/test_notifications.py tests/test_watch_focus.py tests/test_watch_queue.py -q && ruff check app tests`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/repositories backend/app/services backend/tests
git commit -m "feat(backend): scope personal services and watcher to users"
```

---

### Task 5: Scope the read APIs and profile status to the current user

**Files:**
- Modify: `backend/app/api/v1/status.py`, `games.py`, `campaigns.py`, `streams.py`, `progress.py`, `watch_queue.py`, `watcher.py`, `notifications.py`, `scans.py`
- Modify: `backend/app/repositories/games.py`, `campaigns.py`, `streams.py`, `backend/app/domain/schemas.py`
- Test: update `backend/tests/test_status_api.py`, `test_streams_api.py`; create `backend/tests/test_isolation_api.py`

**Interfaces:**
- `CurrentUserDep`, `AdminUserDep`; every personal endpoint takes the current user.
- `/games` returns global catalog with per-user `selected`.
- `PUT /games` replaces only the current user's selections.
- `/campaigns` and `/streams` filter by the current user's selected games/completions.
- `/status` returns `user`, `telegram_ready`, and per-user selected games/counts.
- `/twitch/status` returns `reconnect_required`, `last_error`, `last_synced_at`.
- `POST /scans` requires admin; `POST /notifications/test` uses the current user's chat id.

- [ ] **Step 1: Write failing API isolation tests**

Create two users and assert `/games`, `/campaigns`, `/streams`, `/status`, `/progress`, `/watch-queue`, `/watcher` show only the caller's personal state. Non-admin scan -> 403. No session -> 401.

- [ ] **Step 2: Run tests**

Expected: FAIL on missing auth or global data.

- [ ] **Step 3: Implement scoped endpoints**

Pass the current user through. Remove all `Game.selected`-based personal reads from API/repository paths; use `UserGameRepository`. Keep shared catalog counts where appropriate.

- [ ] **Step 4: Update schemas**

Add `user: AuthUserOut | None`, `telegram_ready: bool`, and Twitch reconnect fields.

- [ ] **Step 5: Verify**

Run: `cd backend && PYTHONPATH=$PWD pytest tests/test_status_api.py tests/test_streams_api.py tests/test_isolation_api.py -q && ruff check app tests`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1 backend/app/repositories/games.py backend/app/repositories/campaigns.py backend/app/repositories/streams.py backend/app/domain/schemas.py backend/tests
git commit -m "feat(api): scope personal reads to the signed-in user"
```

---

### Task 6: Update scan and worker loops for all users

**Files:**
- Modify: `backend/app/services/scan_service.py`, `backend/app/worker/scheduler.py`
- Modify: `backend/app/providers/telegram.py`
- Modify: `backend/app/api/v1/health.py` if provider readiness changes
- Test: update `backend/tests/test_scan_service.py`, create `backend/tests/test_worker.py`, `backend/tests/test_telegram.py`

**Interfaces:**
- Scan uses `UserGameRepository.list_union_names()` and creates starts only for tracking + Telegram-ready users.
- `run_progress` loops active connected user ids; one fresh session per user.
- `run_watcher` loops users with focus enabled; one fresh session per user.
- `TelegramProvider.send(message: str, chat_id: str)`; `configured` = bot token present; sanitized errors.

- [ ] **Step 1: Write failing worker/Telegram tests**

Cover: scan creates starts only for opted-in tracking users; progress loop continues after one user fails; watcher loops only enabled users; Telegram sends to the requested chat id; a failing Telegram response does not contain the bot token in the exception/log.

- [ ] **Step 2: Run tests**

Expected: FAIL.

- [ ] **Step 3: Implement scan and worker changes**

Use per-user sessions and try/except. Mark `reconnect_required` on user-token failures only. Session cleanup runs in the scan job. Redact Telegram URLs/tokens.

- [ ] **Step 4: Verify**

Run: `cd backend && PYTHONPATH=$PWD pytest tests/test_scan_service.py tests/test_worker.py tests/test_telegram.py -q && ruff check app tests`
Expected: PASS.

- [ ] **Step 5: Remove the legacy model classes that no longer have callers**

Delete `TwitchAuth`, `TwitchProfile`, `WatchFocus`, `DropProgress`, `ProgressSnapshot`, `CampaignCompletion`, `Notification`, and `CampaignStart` only after a grep shows no app/test imports. The legacy tables stay in existing databases; do not drop them.

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && PYTHONPATH=$PWD pytest -q && ruff check app tests`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scan_service.py backend/app/worker/scheduler.py backend/app/providers/telegram.py backend/app/api/v1/health.py backend/tests
git commit -m "feat(worker): sync progress and watcher per user"
```

---

### Task 7: Add the frontend auth gate and per-user cache isolation

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/hooks/useApi.ts`, `frontend/src/components/TwitchConnect.tsx`, `frontend/src/App.tsx`, `frontend/src/main.tsx`
- Create: `frontend/src/auth/AuthContext.tsx`, `frontend/src/pages/AuthPage.tsx`, `frontend/src/components/AuthGate.tsx`
- Test: `npm run build`; manual A -> logout -> B check in the browser is required before completion.

**Interfaces:**
- `ApiError { status }`; `credentials: 'include'`; reads `tdm_csrf` and sends `X-CSRF-Token` on unsafe methods.
- `AuthProvider` exposes `{ user, isLoading, login, logout, refresh }`.
- Query keys include `user.id`: `['u', user.id, 'status']`, `['u', user.id, 'games']`, etc.
- On logout/user change: `cancelQueries`, `queryClient.clear()`, reset local UI state.
- `AuthPage` shows Twitch authorize/paste + invite code when `registration.invite_required`, or a closed message when registration is closed.

- [ ] **Step 1: Add API types and client**
- [ ] **Step 2: Add AuthContext/AuthGate and wrap the app**
- [ ] **Step 3: Extend Twitch connect for invite code and login**
- [ ] **Step 4: Scope query keys and clear caches**
- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): add Twitch login gate and user-scoped query cache"
```

---

### Task 8: Add per-user Telegram and admin UI

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`, `SettingsPage.tsx`, `frontend/src/hooks/useApi.ts`, `frontend/src/api/types.ts`, `frontend/src/index.css`
- Test: `npm run build`; manual checks in the browser.

**Interfaces:**
- Settings: Telegram chat id field, opt-in toggle, test button; admin-only Users list with enable/disable; scan button visible only to admins.
- Profile: signed-in local account, Twitch connection, reconnect, sign out, disconnect. Remove "no local user accounts" copy.

- [ ] **Step 1: Add Telegram and admin hooks/types**
- [ ] **Step 2: Update Settings and Profile**
- [ ] **Step 3: Build and manually verify**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): add per-user Telegram and admin controls"
```

---

### Task 9: Update deployment configuration

**Files:**
- Modify: `infra/docker-compose.yml`, `frontend/nginx.conf`, `.env.example`
- Test: `docker compose --project-directory infra -f infra/docker-compose.yml config -q`

**Interfaces:**
- Add `REGISTRATION_CODE`, `REGISTRATION_OPEN`, `OWNER_TWITCH_ID`, `SESSION_TTL_DAYS`, `SESSION_COOKIE_SECURE`, `PUBLIC_ORIGIN`, `ALLOWED_HOSTS`, `AUTH_RATE_LIMIT_PER_MINUTE` to `x-backend-env`.
- Remove `API_TOKEN` and the `VITE_API_TOKEN` build arg. Keep the htpasswd mount for the staged basic-auth period; document its removal.
- nginx preserves inbound `X-Forwarded-Proto` with a `map` and falls back to `$scheme`.

- [ ] **Step 1: Update compose/env**
- [ ] **Step 2: Update nginx**
- [ ] **Step 3: Validate compose config**
- [ ] **Step 4: Commit**

```bash
git add infra/docker-compose.yml frontend/nginx.conf .env.example
git commit -m "feat(infra): configure multi-user auth deployment"
```

---

### Task 10: Update documentation and ADR

**Files:**
- Modify: `docs/API.md`, `DATA_MODEL.md`, `BACKEND.md`, `ARCHITECTURE.md`, `FRONTEND.md`, `OPERATIONS.md`, `DECISIONS.md`, `README.md`, `AGENTS.md`, `STATUS.md`, `CHANGELOG.md`

**Interfaces:**
- Add ADR-019 superseding ADR-009 and the single-user statement in `AGENTS.md`.
- Document env vars, registration rules, backup/migration/rollback, per-user Telegram, basic-auth removal, and the new API contract.

- [ ] **Step 1: Update the docs**
- [ ] **Step 2: Check no stale "single-user"/"no local user accounts" copy remains**
- [ ] **Step 3: Commit**

```bash
git add docs README.md AGENTS.md
git commit -m "docs: document multi-user accounts and deployment"
```

---

### Task 11: Integrate, verify, and review

**Files:** all changed files.

- [ ] **Step 1: Merge the lane branches in order: auth -> scope -> frontend -> deployment/docs.**
- [ ] **Step 2: Run backend tests and ruff.**

```bash
cd backend && PYTHONPATH=$PWD pytest -q && ruff check app tests
```

- [ ] **Step 3: Run the frontend build.**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Review the full diff with a fresh reviewer.** Fix Critical/Important findings.
- [ ] **Step 5: Produce the deployment/env report for the owner. Do not deploy.**
