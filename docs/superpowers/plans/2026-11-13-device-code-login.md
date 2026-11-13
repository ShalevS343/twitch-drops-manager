# Device-Code Twitch Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a Smart TV device-code login so phone users enter an 8-character code at `twitch.tv/activate` instead of copying a redirect token, without breaking the existing implicit flow or existing Android-client accounts.

**Architecture:** Add `twitch_accounts.client_id` and `twitch_device_flows`; refactor login into a shared completion path; add device start/poll APIs; make GQL use each account's issuing client id; add a code UI with `sessionStorage` resume and keep the URL-paste flow as an advanced fallback.

**Tech Stack:** FastAPI, async SQLAlchemy/SQLite (idempotent ALTER), axios/httpx, React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-11-13-device-code-login-design.md`

## Global Constraints

- Existing implicit login must keep working for Android-client tokens.
- No secrets in logs/API responses; `device_code` stays server-side.
- One idempotent SQLite migration; no Alembic; never drop legacy tables.
- Device code TTL 30 minutes, single-use; poll cadence enforced server-side.
- Session/CSRF/invite/admin/isolation/rate-limit behavior unchanged.
- Backend gate: `PYTHONPATH=$PWD /tmp/opencode/tdm-venv/bin/pytest -q && PYTHONPATH=$PWD /tmp/opencode/tdm-venv/bin/ruff check app tests`
- Frontend gate: `npm run build`.
- Do not deploy until the full suite and a real device-flow inventory sync are verified.

## Review Focus

1. Existing implicit accounts still choose the Android client id and sync.
2. Device-flow accounts store the Smart TV client id and GQL uses it.
3. The SQLite ALTER is idempotent and preserves all existing rows.
4. `slow_down`/duplicate polling cannot exceed Twitch's cadence.
5. Phone tab reload/Twitch-app switch can resume a pending flow.

---

### Task 1: Schema, migration, and per-account client id

**Files:** `backend/app/domain/models.py`, `backend/app/core/db.py`, `backend/app/core/migrations.py`, `backend/app/core/config.py`, `backend/app/repositories/twitch_accounts.py`, tests.

**Interfaces:**
- `TwitchAccount.client_id: str` (default `""`).
- `TwitchDeviceFlow` model with fields from the design.
- `run_schema_migrations(connection)` called inside `init_db`.
- `settings.twitch_device_grant_client_id` default `ue6666qo983tsx6so1t0vnawi233wa`.
- `TwitchAccountRepository.save(..., client_id: str = "")`.
- `TwitchAccountRepository.get_client_id(user_id) -> str`.

- [ ] Write failing tests: existing `twitch_accounts` fixture without `client_id`; run migration twice; column exists, rows preserved, no-op rerun. Fresh DB has column. Device-flow table exists.
- [ ] Implement model, settings, migration helper; call it in `init_db` in the same transaction after `create_all`.
- [ ] Update repo save/get and existing call sites with the Android client id.
- [ ] Run focused tests, full suite, ruff. Commit.

### Task 2: Provider device flow + shared login completion

**Files:** `backend/app/providers/twitch_user.py`, `backend/app/services/auth_service.py`, `backend/app/services/progress_service.py`, `backend/app/services/profile_service.py`, `backend/app/domain/schemas.py`, tests.

**Interfaces:**
- `TwitchUserProvider.start_device_flow() -> dict` (POST `/oauth2/device`, Smart TV client).
- `poll_device_token(device_code, client_id) -> dict` (raises typed pending/slow-down/terminal errors).
- `fetch_inventory(access_token, client_id: str = "")`, `fetch_profile(..., client_id="")`; headers use the supplied client id.
- `AuthService.complete_login(token, info, *, invite_code, current_user, client_id) -> AuthResult` shared by implicit and device paths.
- Implicit path asserts Android client id; device path asserts Smart TV client id.
- `ProgressService`/`ProfileService` pass `account.client_id or settings.gql_client_id`.

- [ ] Add failing tests for header client id selection, implicit regression, device token validation/client check, shared login (existing/new/invite/conflict/disabled).
- [ ] Implement provider methods and header threading; refactor `connect` to call `complete_login`.
- [ ] Store `client_id` on every token save; existing empty rows fall back to Android.
- [ ] Run focused tests, full suite, ruff. Commit.

### Task 3: Device flow table/service/API + cleanup

**Files:** `backend/app/repositories/twitch_device_flows.py`, `backend/app/services/twitch_device_service.py`, `backend/app/api/v1/auth.py`, `backend/app/worker/scheduler.py`, tests.

**Interfaces:**
- `POST /auth/twitch/device/start` -> `{flow_id, user_code, verification_uri, expires_at, interval}`.
- `POST /auth/twitch/device/poll` `{flow_id}` -> `{status:"pending", interval}` or `AuthConnectOut` + cookies.
- `POST /auth/twitch/device/cancel` `{flow_id}` -> cancel.
- `TwitchDeviceService.start/poll/cancel`; cleanup expired rows on start + scan.
- Poll enforces `last_polled_at + interval_seconds`; `slow_down` increases interval.

- [ ] Write failing tests: start shape, pending, slow_down interval update, duplicate poll throttle, success cookies/user, denied/expired, cancel, one-time, invite gate, current-user conflict, cleanup.
- [ ] Implement repo/service/API; rate limits; never log device code/token.
- [ ] Run focused tests, full suite, ruff. Commit.

### Task 4: Frontend code-login UI + advanced fallback

**Files:** `frontend/src/api/client.ts`, `types.ts`, `hooks/useApi.ts`, `auth/AuthContext.tsx`, `components/TwitchConnect.tsx` (or new `DeviceConnect.tsx`), `pages/AuthPage.tsx`, `pages/ProfilePage.tsx`, `pages/SettingsPage.tsx`, `index.css`.

**Interfaces:**
- `api.startTwitchDevice(inviteCode?)`, `api.pollTwitchDevice(flowId)`, `api.cancelTwitchDevice(flowId)`.
- `DeviceConnect` controller: start, code state, `sessionStorage` resume, interval polling, cancel, success refresh.
- Primary Connect action uses code flow; URL-paste remains under Advanced.
- Copy-code button with clipboard fallback; activation link.

- [ ] Add API/types/hooks.
- [ ] Add DeviceConnect UI and wire AuthPage/Profile/Settings.
- [ ] Build, manual state check. Commit.

### Task 5: Docs, ADR, integration, live verification

**Files:** `docs/API.md`, `DATA_MODEL.md`, `BACKEND.md`, `FRONTEND.md`, `OPERATIONS.md`, `DECISIONS.md`, `STATUS.md`, `CHANGELOG.md`, `README.md`, `AGENTS.md`.

- [ ] Add ADR-021; document migration, endpoints, env, fallback, phone flow, client id.
- [ ] Merge lanes; full backend suite, ruff, frontend build, compose config.
- [ ] Deploy with WAL-safe backup. Verify `PRAGMA table_info(twitch_accounts)` has `client_id`; existing owner syncs; then connect a phone via code and confirm the first inventory sync succeeds with the Smart TV client id.
- [ ] Fresh reviewer on the full diff; fix findings; push.
