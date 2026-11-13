# Architecture decisions (ADRs)

## ADR-001 — SQLite instead of Postgres

**Context:** single-user Raspberry Pi deployment; the original stack used a
Postgres container that was empty and orphaned after the switch.

**Decision:** use SQLite (`aiosqlite`, WAL) in the shared `drops_data` volume.

**Consequences:** one file to back up, no DB service, simple local dev. Writes are
serialized; avoid multiple writers. Move to Postgres only if the project becomes
multi-user or write-heavy (the async SQLAlchemy layer is portable).

## ADR-002 — Read-only Twitch; never auto-claim/view

**Context:** users want drop rewards, and tooling exists to fake watching.

**Decision:** the app never claims drops and never automates viewing. It only
reads inventory/progress and links to Twitch.

**Consequences:** ToS-safe; user still watches manually. Do not add claim
mutations or watch heartbeats without an explicit product/legal decision.

## ADR-003 — Progress via Twitch internal GQL + first-party implicit login

**Context:** Helix has no drops-progress endpoint. Twitch's web Drops page uses
internal GQL. Twitch GQL rejects tokens issued to third-party apps.

**Decision:** use Twitch's own Android/first-party public client for an implicit
grant; the user authorizes once and pastes the redirect URL. Store the token in
`twitch_auth`; query `Inventory` (with a raw-query fallback) and `ViewerCard` for
the profile. Never persist passwords.

**Consequences:** works with real accounts, no client secret for progress, but
depends on an unofficial API and a first-party client id that Twitch may rotate.
Device-code flow was tried and rejected because GQL returned 401 for third-party
tokens. (The Smart TV device grant is now the primary login; see ADR-021.)

## ADR-004 — Telegram digests + atomic dedupe

**Context:** one message per stream/drop caused bursts (5 stream messages at once)
and API/worker races could duplicate sends.

**Decision:** claim a dedupe key inside a SQLite SAVEPOINT **before** sending; send
one digest per scan/progress run; release claims if Telegram fails. Deadline
reminders use only the tightest window (2h over 24h).

**Consequences:** no duplicate messages, fewer messages, retry on failure. Claims
persist in `notifications`; a failed send does not silently lose the event.

## ADR-005 — Monitoring via Docker labels + kuma-sync

**Context:** Uptime Kuma has no simple declarative Docker discovery out of the box.

**Decision:** label services with `kuma.enable=true`, `kuma.name`, `kuma.port`,
`kuma.type=tcp`; the local `kuma-sync` container creates TCP monitors by name.

**Consequences:** monitors are reproducible when containers are recreated; the
label must be on the running container (recreate after compose changes).

## ADR-006 — Solid industrial UI, no gradients/glows

**Context:** the first dashboard used the generic dark-purple gradient/glow +
rounded-outline-icon style.

**Decision:** solid graphite surfaces, amber accent, square geometry, serif
display headings, mono labels, custom filled/geometric icons. No gradients, glows,
backdrop blur, or pill components.

**Consequences:** distinctive, readable, less "template" looking. New UI work must
use the tokens in `frontend/src/index.css` and not reintroduce the old styles.

## ADR-007 — Hash tabs, no router dependency

**Context:** seven top-level views; avoid adding react-router for a small app.

**Decision:** tabs are `#/route` hashes with `useTab`; invalid hashes canonicalize
to `#/overview`.

**Consequences:** refresh/deep links work; no dependency. If nested routes or
params grow, consider a router.

## ADR-008 — Flat read queries + deferred raw JSON

**Context:** `/watch-queue` took ~100 ms because it loaded every campaign, its
rewards, and 715 KB of `raw` JSON just to map ids.

**Decision:** read paths use flat joins/lightweight columns; `Campaign.raw` is
deferred (write-only). Keep explicit loaders for endpoints that need graphs.

**Consequences:** watch queue 100 → 18 ms, streams 6 → 1 query. Future read paths
should follow the same pattern; see `docs/backend-performance.md`.

## ADR-009 — No local user accounts (superseded by ADR-019)

**Context:** the UI needs a profile, but the app is single-user.

**Decision:** display the Twitch account from the OAuth token; persist only
`twitch_auth` + a small `twitch_profile` cache. No users table, password login, or
multi-account logic.

**Consequences:** simple auth; reconnect replaces the single token. Multi-user
support required a new design; see ADR-019.

## ADR-010 — Portainer git deployment

**Context:** the live stack is managed on the Pi via Portainer, while development
happens in `/opt/...` and worktrees.

**Decision:** `main` is the source of truth; deploy via Portainer "Pull and
redeploy". Manual compose runs use the same project name.

**Consequences:** DB volume/network persist. Portainer may show drift after manual
compose operations; prefer Portainer for production.

## ADR-011 — Track games by name + campaign-start ledger

**Context:** users want alerts for games that have no current campaign, or whose
campaign ended and will return. The catalog only contains current campaigns, and a
single failed Telegram send must not lose a start event.

**Decision:** `PUT /games` creates a `Game` row for any selected name, so tracking
does not depend on catalog presence. Scans compare each campaign's previous status
with the incoming status; a transition to `ACTIVE` for a selected game creates a
`campaign_starts` row. The notification send claims
`campaign-started:{external_id}`, sends starts (live-stream alerts were removed
in ADR-016), deletes the pending row on success, and leaves it for retry on
failure.

**Consequences:** a start is reported once across processes; a Telegram outage
delays but does not drop alerts. Campaigns that were already `ACTIVE` when a game
is first tracked do not generate a start (there is no transition). Orphan rows are
pruned each scan.

## ADR-012 — Violet high-contrast UI (supersedes ADR-006 palette)

**Context:** the graphite/amber pass was reported as hard to read: yellow accent,
small/cluttered type, and dark text on dark surfaces.

**Decision:** keep the solid industrial structure (no gradients/glows/pills) but
move the accent to Twitch violet (`#9146ff`), raise the type scale (15px body,
1.85rem page titles), use near-white copy/brighter muted grays and lighter
surfaces, and make the brand mark/favicon/avatars circular. Mono is reserved for
numeric/technical values.

**Consequences:** better contrast and readability on desktop and mobile. New UI
work must use the current `:root` tokens; do not reintroduce amber or micro
uppercase/mono labels.

## ADR-013 — Manual watch sessions only (superseded by ADR-017)

**Context:** the watch queue makes it easy to find the right stream, but tracking
how long you have actually been watching is manual. Automating playback or
simulated viewing would cross the read-only/ToS boundary.

**Decision:** add a browser-local session timer. Starting a session stores the
stream/campaign and a timestamp in `localStorage`, opens the real stream in a new
tab, and shows elapsed time against the campaign’s remaining watch minutes. It
supports pause/resume/stop and at most one session. On target, the UI suggests
the next campaign but requires an explicit switch. No playback control, watch
heartbeats, or fake viewing events are sent.

**Consequences:** the timer is a convenience, not proof of viewing; it can
overstate elapsed time if left running after you stop watching, which is why the
UI requires manual pause/stop. State is per-browser, not synced to the backend.

## ADR-014 — Top-N per game in live lists

**Context:** scans can match hundreds of live streams, making the queue and
streams pages long and hard to scan.

**Decision:** group live cards by game and show at most 5 per game by default,
with a 5/10/20/All selector. Limiting is client-side after filtering so search
still sees the full loaded set. Group order preserves the page’s sort (urgency or
viewers).

**Consequences:** the default view stays short without changing backend
contracts. Selecting All restores the complete list; future server-side limits
would need a total-count contract to keep the “showing X of Y” copy accurate.

## ADR-015 — Single focused watcher over the queue (focus pointer only)

**Context:** the watch queue is urgency-sorted, but the user still has to decide
which live stream to keep in front of them. Auto-playing or simulating viewing
would cross the read-only/ToS boundary (ADR-002, ADR-013).

**Decision:** add a persisted **focused watcher** that selects one live
stream/campaign pair from the queue. Focused mode allows exactly one watcher
(`watch_focus` singleton row). It can be enabled/disabled, dispatched manually,
auto-picked from the most urgent campaign, or moved to the next live with
`POST /watcher/focus`. The worker reconciles every `WATCHER_POLL_SECONDS`:
if the focused live leaves the queue while the campaign still has time, it sends
one Telegram notification per online session, keeps the target, and sets
`status=offline` (it does **not** auto-move). If the campaign completes, it sends
one completion notification and turns focused mode off.

**Consequences:** focus is a monitoring pointer, not a timer or playback
controller. The user manually picks another live after an offline alert. Stream
ids change on every scan, so reconciliation matches `user_login` + `campaign_id`
first. Notification claims are released on Telegram failure so the next
reconcile retries. Each user has one focused watcher; ADR-019 moved the focus row
from a singleton to a per-user key.

## ADR-016 — No Telegram alerts for new live streams

**Context:** scan-level stream discovery produced stream digests that spam the
bot. The user only wants campaign-start alerts and focused-watcher events.

**Decision:** the scan notification path only sends pending campaign starts. It
never claims or sends live-stream alerts. Discovered streams are still stored and
shown in the watch queue/streams UI. Focused-watcher notifications are separate
and are limited to an offline target and campaign completion.

**Consequences:** no “Live now” messages at all. The `notifications` ledger is
used for `campaign-started:*`, `watch-offline:*`, and `watch-complete:*`. When
Telegram fails, the campaign-start claim is released and the start row remains
for retry.

## ADR-018 — Persist campaign completion from earnedDropRewards

**Context:** Twitch's `dropCampaignsInProgress` no longer returns a campaign once
all rewards are claimed, so matching completion against current progress misses
campaigns the user already finished. Catalog status can still say `ACTIVE`.

**Decision:** fetch the Inventory query with `fetchRewardCampaigns: true`, which
adds `earnedDropRewards`. The progress sync groups claimed rewards by campaign
and compares the count with the catalog campaign's reward count. Fully claimed
campaigns are written to the `campaign_completions` ledger and never removed.
`GET /campaigns` exposes `completed`; `GET /progress` appends ledger campaigns
(from catalog rewards) so they still render with all drops claimed.

**Consequences:** completion survives the campaign leaving Twitch's in-progress
inventory and `drop_progress` replacement. The UI can label completed campaigns
instead of showing them as active. The ledger is only as accurate as the catalog
reward count and Twitch's claimed reward list; partial claims stay incomplete.

## ADR-019 — Twitch-as-login, server sessions, per-user data (supersedes ADR-009)

**Context:** the app was hard-wired to one Twitch account (`twitch_auth`), but a
small group now needs its own progress, selected games, focus target, and
Telegram destination. A password/email account system would add a second identity
store, reset flows, and a new security surface for no product gain: Twitch
already proves identity.

**Decision:**

- **Twitch is the only identity provider.** There are no passwords, email
  accounts, or local recovery. A local `users` row is permanently keyed by the
  Twitch numeric user id (required, unique); signing in with a different Twitch
  account creates or loads a different local user.
- **Server-side sessions.** The implicit-grant token is validated with Twitch,
  stored on `twitch_accounts`, and exchanged for an opaque 32-byte session token
  in an `HttpOnly` `tdm_session` cookie. Only the SHA-256 hash is stored in
  `user_sessions`. A readable `tdm_csrf` cookie must be echoed as
  `X-CSRF-Token` on every unsafe method. Cookies are `SameSite=Lax`, `Path=/`,
  and `Secure` per `SESSION_COOKIE_SECURE` (Compose default `true`; `auto` can
  derive it from a trusted forwarded scheme). Sessions have an absolute
  `SESSION_TTL_DAYS` (30) lifetime and do not slide.
- **Per-user personal data.** Selected games, Twitch token/profile, drop
  progress, snapshots, completions, watch focus, campaign starts, and
  notification claims live in `user_*` tables keyed by `user_id`. The catalog
  (`games`, `campaigns`, `rewards`), live streams/matches, and scan runs stay
  shared and are scanned once.
- **Per-user Telegram.** One bot token in env; each user links a private chat
  through a one-time deep link and stores an optional opt-in flag.
  `TELEGRAM_CHAT_ID` only seeds the migrating owner. The chat id is read-only;
  only the link flow can set it. Disabling Telegram deletes that user's pending
  start rows.
- **Invite-only registration.** The first admin needs a matching
  `OWNER_TWITCH_ID`, a valid `REGISTRATION_CODE`, or
  `REGISTRATION_OPEN=true`; an empty DB is not implicitly open. Later users need
  the code unless registration is explicitly open. Admins can list users,
  enable/disable them, and trigger global scans; admins cannot disable
  themselves.
- **Legacy migration.** `init_db()` runs a single-transaction, idempotent
  migration that copies the old single-user rows to the owner's user id, keyed
  by `app_meta['multi_user_v1']`. An empty legacy `user_id` or a conflicting user
  aborts with an operator error rather than guessing. Legacy tables are frozen
  (not dropped) for rollback; new writes only go to the user-keyed tables.
- **`API_TOKEN` / `X-API-Token` is retired.** Session cookies and roles replace
  it. `/health` stays public; all other endpoints require a session except the
  public auth endpoints.

**Consequences:** the browser never holds a Twitch token, and one user cannot
read another's personal data. The deployment needs a pre-upgrade WAL-safe backup:
rolling back to the old release reads the frozen legacy tables, so keeping
post-upgrade data requires restoring the pre-upgrade backup. Twitch tokens remain
plaintext in SQLite, so the volume/host stays the security boundary. The schema
is user-keyed for future growth, but one SQLite writer and sequential per-user
Twitch calls remain the practical ceiling (dozens of users); Postgres and a job
queue are later options.

## ADR-020 — Security hardening after the multi-user audit

**Context:** an independent audit of the multi-user/auth/Telegram release found
two High and several Medium issues: a first-run admin/invite bypass, Twitch client
secret leakage through provider/scan errors, Telegram link-code destination
replacement, missing endpoint cooldowns, a shared auth-rate-limit DoS path,
unbounded game selection input, stored-XSS risk from API-controlled URLs, missing
browser security headers, plaintext LAN exposure, and secret-backup handling.

**Decision:**

- **Bootstrap is gated.** An empty `users` table is not open. The first admin
  needs matching `OWNER_TWITCH_ID`, a valid `REGISTRATION_CODE`, or explicit
  `REGISTRATION_OPEN=true`; the admin claim stays atomic.
- **Provider errors are sanitized.** Twitch credentials go in the POST body, and
  provider/scan errors never include URLs, request bodies, tokens, or upstream
  response bodies. `/status` and `/scans/latest` expose only safe error text.
- **Telegram links cannot replace a destination.** A code may re-link the same
  chat but cannot overwrite a different existing chat; disabled accounts cannot
  drive commands; repeated commands are cooldown-limited.
- **Rate limits have two layers.** Per-IP auth limiting plus a deployment-wide
  ceiling, and per-user cooldowns on expensive/abusable actions.
- **Input is bounded.** Selected-game count and name length are capped before
  touching the shared catalog.
- **Browser output is constrained.** API-controlled URLs are rendered only for
  `http:`/`https:`, and nginx adds CSP/HSTS/nosniff/frame-deny/referrer/
  permissions headers.
- **The deployment is not LAN-plaintext.** The frontend binds `127.0.0.1:8282`;
  Funnel is the public TLS entry point. `SESSION_COOKIE_SECURE` defaults to
  `true`.
- **Secret backups are excluded.** `.env.*` is gitignored except `.env.example`,
  and `.env` is `chmod 600`.

**Consequences:** the app is safer to expose publicly, but local HTTP access now
needs an explicit `SESSION_COOKIE_SECURE=false`/`auto` override and direct LAN
access is intentionally unavailable. In-process limiters assume the current
single-worker deployment. CSRF remains double-submit rather than session-bound,
and a Twitch client-secret/Telegram-token rotation is still an operator action if
an old build ever logged them.

## ADR-021 — Device-code Twitch login for phones

**Context:** the implicit grant redirects to
`https://www.twitch.tv/#access_token=...`; the Twitch mobile app swallows that URL,
so phone users have no address bar to copy from. Twitch's Smart TV public client
accepts the device authorization grant, and GQL accepts the resulting token with
that client id.

**Decision:** add a device-code login as the primary **Connect Twitch** flow:

- `POST /auth/twitch/device/start` calls Twitch's `/oauth2/device` with the Smart
  TV client id and no scopes, then stores a short-lived flow row. The browser gets
  only the opaque `flow_id`, the 8-character `user_code`, the activation URI, the
  expiry, and the polling interval. The Twitch `device_code` never leaves the
  server.
- Polling and cancellation use `POST /auth/twitch/device/poll` and
  `POST /auth/twitch/device/cancel` with `{"flow_id": "..."}` in the body, so the
  bearer flow id does not appear in Uvicorn/access-log request lines.
- The server owns the poll cadence. An atomic conditional update on
  `last_polled_at` admits one upstream poll per interval; duplicate tabs get
  `pending` without contacting Twitch. `slow_down` increases and persists the
  interval. Transient Twitch/network failures keep the flow pending.
- Flows expire after 30 minutes, are single-use, and are cleaned up on start and
  during the worker scan. The registration gate, first-admin claim, disabled-user
  check, current-session conflict, sessions, and CSRF remain the same as the
  implicit flow.
- Each `twitch_accounts` row stores the client id that issued its token. Implicit
  logins store the Android client; device logins store the Smart TV client.
  Progress/profile GQL uses `account.client_id`, falling back to the configured
  GQL client for legacy rows.
- The implicit URL-paste flow remains as an advanced fallback. An idempotent
  additive migration adds `twitch_accounts.client_id` and records
  `app_meta['twitch_device_login_v1']`.

**Security risk — device-grant phishing is inherent and not eliminated.** Device
authorization can be abused by code phishing: an attacker starts a flow, sends
the victim the attacker's `user_code`, and the victim may approve it at
`twitch.tv/activate`. The resulting Twitch token/session belongs to the flow the
attacker started. This design reduces the window with a 30-minute TTL, single-use
rows, server-side cadence, and the normal invite/registration gates, and the UI is
required to warn users to enter only codes they generated in this app. Do **not**
describe the flow as phishing-proof. Device tokens also remain plaintext bearer
tokens in SQLite; the volume/host stays the security boundary.

**Consequences:** phones no longer need to copy a redirect URL. The Smart TV
client id is public but unofficial and can rotate, so the first real device-flow
inventory sync must be verified after deploy. Existing Android-client accounts
keep working without reconnecting; first-party GQL behavior remains unofficial.
