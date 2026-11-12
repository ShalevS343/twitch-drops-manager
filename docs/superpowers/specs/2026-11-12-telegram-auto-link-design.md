# Telegram Auto-Link + UI Notice Cleanup — Design

**Date:** 2026-11-12
**Status:** Approved by request ("keep the alerts toggle... keep it on"; remove gray text boxes)

## Intent

Let a signed-in user connect Telegram without leaving the app to hunt for a chat id
or use a third-party bot. The bot also replies with the chat id for anyone who
prefers the manual field. Separately, remove the thin gray `.notice` info strips
that clutter the UI.

## Telegram flow

1. **Settings → Telegram → Connect Telegram** calls `POST /telegram/link`.
2. Backend creates a one-time code (10-minute TTL) tied to the current user and
   returns:
   ```json
   {"deep_link":"https://t.me/raspberrypitwitchbot?start=<code>","expires_at":"..."}
   ```
3. The browser opens the deep link. The user presses **Start**.
4. The worker's long-poll task receives `/start <code>`, validates:
   - the update is a private chat;
   - the code is unused and unexpired;
   - no other active user already owns that chat id.
5. Backend saves `telegram_chat_id` and sets `telegram_enabled=true` (the toggle
   stays visible and can be turned off later), deletes the code, and replies:
   ```text
   Connected to Twitch Drops Manager as <display name>.
   Alerts are on. Send /stop to stop alerts.
   ```
6. Settings polls `/auth/me` until the chat id appears and shows **On**.

Fallbacks:
- `/start` on an unlinked chat points the user to Settings → Connect Telegram.
- `/stop` sets `telegram_enabled=false` for the matching chat id and replies.
- `/unlink` clears the chat id and disables alerts.

**Post-approval update:** the manual chat-id field was removed. The chat id is
read-only and can only be set by completing the link flow; `PATCH /auth/me`
only toggles alerts.

## Transport decision

Use **worker long polling** (`getUpdates`), not a webhook:
- The bot currently has no webhook and 0 pending updates.
- The worker already runs continuously on the Pi.
- No new public endpoint, webhook secret, or Funnel-URL coupling.
- Persist `telegram_update_offset` in `app_meta`; use `timeout=25`.
- If Telegram returns `409 Conflict` (a webhook is set), log a clear admin error
  and stop polling until restart. Never log the token or raw update text.

Accepted tradeoff: one poller and a background task in the worker. If the bot is
later switched to a webhook, the poller must be replaced.

## Data model

New table `telegram_link_codes`:

| Column | Notes |
|---|---|
| `id` | PK |
| `user_id` | FK → users, cascade, indexed |
| `code_hash` | unique, SHA-256 of the URL-safe code |
| `created_at`, `expires_at` | 10-minute TTL |
| `used_at` | nullable; one-time use |

No schema change to `users`; `telegram_chat_id`/`telegram_enabled` already exist.
Enforce one non-empty chat id per user in the link service with a query; do not
add a partial unique index in this phase.

## API

- `POST /telegram/link` (session) -> `TelegramLinkOut {deep_link, expires_at}`.
  Invalidates older unused codes for the same user.
- `POST /telegram/unlink` (session) -> clears chat id, disables alerts, deletes
  pending campaign starts. Optional UI button.
- Existing `PATCH /auth/me` remains the manual fallback.
- `/auth/me` already exposes `telegram_chat_id` and `telegram_enabled`.

## Frontend

- Replace the "Open Telegram, message your bot once, copy your numeric chat ID..."
  copy with:
  - **Connect Telegram** button (deep link + waiting state).
  - A short line: "Prefer manual setup? Open @bot and send /start; it replies
    with your chat id." The numeric field stays available.
  - When linked, toggle defaults to on; user can turn it off.
- Poll `/auth/me` every 3 seconds for up to ~2 minutes while waiting; stop on
  success or cancel.
- Remove all `.notice` gray strips:
  - Profile local-account notice: remove.
  - Profile disconnect notice: remove.
  - Settings missing-bot notice: turn into plain muted text.
  - Settings system notice: remove (the "Managed by .env" badge carries it).
  - Auth closed-registration notice: turn into plain muted text.
  - Remove the `.notice` CSS block if no usages remain.
- Keep colored `.alert-danger/success/warning` feedback; those are actionable.
- Keep the structural `.panel`/`.card` surfaces; they organize data.

## Security

- Private chats only; ignore groups/channels.
- Codes are high-entropy, hashed at rest, one-time, 10-minute TTL, invalidated on
  a new link request.
- Link creation requires a session and is rate-limited by the existing auth
  limiter or a small per-user guard.
- Do not log bot tokens or raw Telegram updates.
- `/stop` and `/unlink` only affect the user owning that chat id.

## Testing

- Link code: create, expiry, one-time use, invalid code, duplicate chat id across
  users, private-chat-only.
- API: session required, deep link shape, unlink clears chat/toggle/starts.
- Poller: `/start <code>` links and replies; `/start` without code replies with
  chat id; `/stop` disables; offset persists; 409 handled without crashing.
- Frontend: build; Settings waiting/linked/manual states; no `.notice` remains.

## Non-goals

- Webhook transport.
- Group/channel linking.
- Telegram command menus or multi-bot support.
- Changing the existing notification content/dedupe logic.
