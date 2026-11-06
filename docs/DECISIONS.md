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
tokens.

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

## ADR-009 — No local user accounts

**Context:** the UI needs a profile, but the app is single-user.

**Decision:** display the Twitch account from the OAuth token; persist only
`twitch_auth` + a small `twitch_profile` cache. No users table, password login, or
multi-account logic.

**Consequences:** simple auth; reconnect replaces the single token. Multi-user
support would require a new design.

## ADR-010 — Portainer git deployment

**Context:** the live stack is managed on the Pi via Portainer, while development
happens in `/opt/...` and worktrees.

**Decision:** `main` is the source of truth; deploy via Portainer "Pull and
redeploy". Manual compose runs use the same project name.

**Consequences:** DB volume/network persist. Portainer may show drift after manual
compose operations; prefer Portainer for production.
