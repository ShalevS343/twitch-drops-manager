# Telegram Auto-Link + Notice Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let users link Telegram with one click/deep link, keep the alerts toggle on by default after linking, and remove the gray `.notice` info strips.

**Architecture:** `POST /telegram/link` creates a one-time code and deep link. A worker long-poll task consumes `/start <code>` via `getUpdates`, validates the private chat, saves `telegram_chat_id`, enables alerts, and replies. No webhook.

**Tech Stack:** FastAPI, async SQLAlchemy/SQLite, Telegram Bot API, APScheduler worker, React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-11-12-telegram-auto-link-design.md`

## Global Constraints

- No new dependencies. No webhook. Private chats only.
- Never log the bot token or raw Telegram update text.
- Keep the existing per-user alerts toggle; linking sets it on, user can turn it off.
- Remove only `.notice` strips, not `.panel`/`.card` structure or colored error/success alerts.
- Backend gate: `PYTHONPATH=$PWD /tmp/opencode/tdm-venv/bin/pytest -q && PYTHONPATH=$PWD /tmp/opencode/tdm-venv/bin/ruff check app tests`
- Frontend gate: `npm run build`.
- Do not deploy/push/merge to main without explicit instruction.

## Review Focus

1. A code must be one-time and user-bound; expired/used codes must not link.
2. Private chats only; groups must never become alert recipients.
3. Duplicate chat ids across users must be rejected or last-writer prevented.
4. Poller failures (409 webhook, network) must not crash the worker or leak tokens.
5. Removing notices must not remove actionable error/success alerts or structural panels.

---

### Task 1: Backend link model, service, API, poller

**Files:**
- Modify: `backend/app/domain/models.py`, `backend/app/repositories/users.py`, `backend/app/domain/schemas.py`, `backend/app/api/v1/router.py`, `backend/app/providers/telegram.py`, `backend/app/worker/scheduler.py`
- Create: `backend/app/repositories/telegram_links.py`, `backend/app/services/telegram_link_service.py`, `backend/app/worker/telegram_poller.py`, `backend/app/api/v1/telegram.py`
- Test: `backend/tests/test_telegram_link.py`, `backend/tests/test_telegram_poller.py`

**Interfaces:**
- `TelegramLinkCode(id, user_id, code_hash, created_at, expires_at, used_at)`.
- `TelegramLinkRepository.create(user_id, code_hash, expires_at)`, `get_by_hash`, `mark_used`, `delete_for_user`, `delete_expired`.
- `TelegramLinkService.create_link(user_id) -> TelegramLinkOut`; `link_chat(code, chat_id, chat_type) -> LinkResult`; `unlink(user_id)`.
- `TelegramProvider.get_me() -> dict`, `get_updates(offset, timeout=25) -> list[dict]`, `send(message, chat_id)`.
- `TelegramPoller.run()` / `stop()`; worker starts it after scheduler start and stops it on shutdown.
- `POST /telegram/link`, `POST /telegram/unlink`.

- [ ] Write failing tests for code creation/deep link, expiry, one-time use, private-only, duplicate chat id, `/start` with/without code, `/stop`, offset persistence, 409 handling.
- [ ] Implement model/repository/service/API/provider methods/poller.
- [ ] Run focused tests, then full backend suite + ruff. Commit.

### Task 2: Frontend Telegram UI + notice cleanup

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/hooks/useApi.ts`, `frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/ProfilePage.tsx`, `frontend/src/pages/AuthPage.tsx`, `frontend/src/index.css`
- Test: `npm run build`; manual Settings states.

**Interfaces:**
- `api.createTelegramLink()`, `api.unlinkTelegram()`; `TelegramLink` type.
- Settings: Connect Telegram button opens deep link, shows waiting state, polls `/auth/me` until linked; toggle on after link. **The manual chat-id field was removed by follow-up: chat id is link-only/read-only.**
- Remove `.notice` usages and CSS; convert closed-registration and missing-bot messages to plain muted text.

- [ ] Add API types/client/hooks.
- [ ] Update Settings UI and polling.
- [ ] Remove notices and CSS.
- [ ] Build and manually verify. Commit.

### Task 3: Integrate and review

- [ ] Merge backend/frontend, run full backend suite + ruff + frontend build.
- [ ] Fresh reviewer checks auto-link security/poller and notice removal.
- [ ] Fix findings, re-run gates, report.
