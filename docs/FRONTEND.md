# Frontend

React 18 + TypeScript + Vite + TanStack Query. Served by nginx in production on
**127.0.0.1:8282** (loopback); Tailscale Funnel provides the public HTTPS URL. No
router dependency; tabs are hash routes.

## Structure

```
frontend/src/
  App.tsx                    shell: sidebar, topbar, tabs, toasts
  api/
    client.ts                fetch wrapper: credentials, CSRF, ApiError
    types.ts                 contracts mirrored from backend schemas
  auth/
    AuthContext.tsx          current user, login/logout/refresh
  components/
    AuthGate.tsx             sign-in screen vs dashboard
    CampaignCard.tsx
    ProgressCard.tsx
    StreamCard.tsx
    WatchFocusPanel.tsx     single focused watcher, dispatch/next/stop
    WatchQueueCard.tsx       start watching = open stream + focus target
    DeviceConnect.tsx        code-login controller + waiting UI (sessionStorage resume)
    TwitchConnect.tsx        legacy authorize/paste flow, hook, advanced disclosure
    GameSelector.tsx
    ui/                      Avatar, Badge, EmptyState, Icon, PageHeader,
                             PerGameSelect, Spinner, StatCard, TabNav
  hooks/
    useApi.ts                TanStack Query hooks + query result types
    useTab.ts                hash routing with canonicalization
  lib/
    campaigns.ts             phase/percent helpers
    format.ts                date/time/remaining formatters
    streamGroups.ts          per-game limiting/grouping helpers
    tabs.ts                  tab ids + metadata
    url.ts                   safe http(s) URL checks for API-provided links
  pages/
    AuthPage.tsx             code login (primary) + invite code + advanced paste
    OverviewPage.tsx
    CampaignsPage.tsx
    ProgressPage.tsx
    WatchQueuePage.tsx
    StreamsPage.tsx
    SettingsPage.tsx
    ProfilePage.tsx
  index.css                  design system + all component styles
  main.tsx                   QueryClientProvider + AuthProvider
```

## Auth gate

`AuthGate` calls `GET /auth/me`; without a session it renders `AuthPage` instead
of the dashboard. The sign-in screen leads with the device-code flow
(`DeviceConnect`) and shows the invite-code field only when
`registration.invite_required` is true and registration is open. When
registration is closed it shows a "registration closed" message; existing
accounts can still sign in with a code. The legacy authorize/paste flow is kept
under an **Advanced / desktop** disclosure.

`AuthContext` exposes `{ user, isLoading, login, logout, refresh }`. After a
successful connect, both cookies are set, `/auth/me` refreshes, and all data
queries load for that user. `POST /auth/logout` ends the session and returns to
the gate.

Tabs are unchanged after sign-in.

### URL safety and session freshness

Any URL supplied by the API is normalized through `lib/url.ts` before it reaches
an `href` or `src`. `safeExternalUrl(value)` parses with `new URL(value,
window.location.origin)` and returns the normalized URL only for `http:` or
`https:`; missing, malformed, `javascript:`, `data:`, `vbscript:`, and
protocol-relative/backslash values return `null`. This covers campaign
`details_url`, live stream URLs, the Twitch authorize URL, Telegram
`deep_link`, and profile images. Unsafe links are not rendered as anchors: the
campaign footer falls back to plain campaign-name text, and unsafe stream links,
authorize links, and avatars are omitted or replaced by their plain-text/initial
fallbacks. External anchors use `target="_blank"` with
`rel="noopener noreferrer"`.

`AuthContext` re-checks `/auth/me` on `focus`, `visibilitychange`, and `pageshow`.
The `pageshow` handler is limited to `event.persisted` restores, because a
BFCache-restored page keeps its frozen React state and could otherwise keep
showing the previous authenticated user; a normal load already runs the initial
`/auth/me` check. All three listeners are removed on unmount.

## Tabs

Hash routes, default `#/overview`; invalid hashes are normalized:

| Route | Page | Purpose |
|---|---|---|
| `#/overview` | Overview | Stats, needs attention, queue preview, campaign progress |
| `#/campaigns` | Campaigns | Catalog with search/game/status filters |
| `#/progress` | Progress | Personal drop progress and ready-to-claim status |
| `#/watch-queue` | Watch queue | Urgency-sorted eligible streams, grouped by game, top 5 per game by default |
| `#/streams` | Streams | Live streams that still advance an uncompleted campaign, filtered/grouped, top 5 per game by default |
| `#/settings` | Settings | Games (including track-by-name), per-user Telegram, admin Users (admin only), Twitch connection, system info |
| `#/profile` | Profile | Local account, Twitch connection/profile, reconnect/disconnect, sign out |

`useTab` uses `window.location.hash` + `hashchange` and `history.replaceState` to
canonicalize. The skip link preserves the active tab (does not change the hash).

## Data fetching

TanStack Query; all requests go through `api/client.ts`:

- `credentials: 'include'` on every request; unsafe methods read the readable
  `tdm_csrf` cookie and send it as `X-CSRF-Token`.
- `ApiError` carries the HTTP status; a `401` clears the cache and returns to the
  auth gate.
- Every personal query key includes the signed-in user id, for example
  `['u', user.id, 'status']`, `['u', user.id, 'progress']`,
  `['u', user.id, 'watch-queue']`. This prevents a shared browser from reusing
  one user's cached data for another.
- On logout or user change: cancel in-flight queries, `queryClient.clear()`, and
  reset local UI state.
- `useAuth()` / `/auth/me` — the session and registration state.
- `useStatus()` — 30s
- `useTwitchStatus()` — 60s (current user)
- `useCampaigns()`, `useStreams()`, `useGames()` — on demand/shared
- `useProgress()` — 60s
- `useWatchQueue()` — 30s
- `useWatcher()` — 15s
- Mutations: save games, scan (admin only), refresh progress, test Telegram,
  watcher enable/focus/next/stop, Telegram settings, admin enable/disable,
  Twitch device start/poll/cancel, Twitch connect/reconnect, logout, disconnect.
- Device login calls `POST /auth/twitch/device/start`,
  `POST /auth/twitch/device/poll`, and `POST /auth/twitch/device/cancel` through
  `api.startTwitchDevice`, `api.pollTwitchDevice`, and
  `api.cancelTwitchDevice`. The opaque `flow_id` travels in the JSON body
  (`{flow_id}`), never in the URL.

Invalidation: scan refreshes all queries; game save refreshes games/campaigns/
status; progress refresh refreshes progress/watch queue/twitch/status; logout
clears everything. Saving a game name that is not cached yet is allowed; the
response/next query reflects the newly created tracked row.

## Authentication flow

### Device code (primary)

1. The user clicks **Connect with code** (AuthPage, Profile, or Settings). On
   AuthPage a required invite code is sent with the request.
2. `POST /auth/twitch/device/start` returns `flow_id`, the 8-character
   `user_code`, `verification_uri`, `expires_at`, and the current poll `interval`.
3. The UI shows the code with **Copy & open Twitch** (copies the code and opens
   `twitch.tv/activate` in a new tab in the same click gesture), links to
   `twitch.tv/activate`, and displays a waiting state. Before the activation
   link, it shows a prominent warning: **Only enter a code you generated in this
   app.** Never enter a code someone sent you. The user enters the code and
   approves the device login on Twitch.
4. The UI polls `POST /auth/twitch/device/poll` with `{flow_id}` every `interval`
   seconds and adopts the interval returned by each pending response (the backend
   raises it on Twitch `slow_down`). Polling stops on success, **Cancel**, a
   terminal error, the local `expires_at` timeout, or unmount. Transient
   `502`/`503`/`504` poll failures are retried up to three times on the current
   interval while keeping the `sessionStorage` record; only after the retries are
   exhausted does the error state clear it.
5. On success the session cookies are already set. The controller refreshes
   `/auth/me`, which purges all caches when the signed-in identity changes, and
   invalidates the user-scoped queries for an in-place reconnect.
6. **Cancel** calls `POST /auth/twitch/device/cancel` with `{flow_id}` as a best
   effort and clears the waiting state.

`start()` refuses to begin another flow while one is already waiting, and the
page-level **Connect with code** / **Reconnect with code** buttons (plus the
advanced URL button) are disabled while `device.flow` exists. The user must
cancel the visible flow rather than silently orphaning it.

While waiting, `DeviceConnect` stores
`{flow_id, user_code, interval, verification_uri}` (plus `expires_at` and the
login/reconnect mode) in `sessionStorage`. Reloading the page or returning from
the Twitch app resumes polling from that record. The record is removed on
success, cancel, expiry, terminal error, or a mode mismatch (a reconnect flow
must not resume on the signed-out gate). If Twitch accepted the code but the
success response never reached this browser, the error state explains that the
confirmation may have been lost and offers **Start a new code**; the stored flow
is already cleared so the user can retry cleanly.

### Advanced / desktop fallback

`TwitchConnect` still implements the implicit grant: `GET
/auth/twitch/authorize`, approve in a new tab, copy the full
`twitch.tv/#access_token=...` URL, then submit `POST /auth/twitch/connect`.
AuthPage, Profile, and Settings keep it inside an **Advanced / desktop**
disclosure. It remains the only flow for existing Android-client tokens and is
not removed by the code flow.

Signed-in users use either flow to reconnect an expired token or to connect
Twitch after a disconnect. Connecting a **different** Twitch account while signed
in returns `409`; the UI tells the user to sign out first. There are no
passwords, and `VITE_API_TOKEN` no longer exists; the browser never holds a
Twitch token.

Fallbacks: initials avatar when the image fails; display name falls back to login;
missing dates render `Unknown`; token expiry can be absent for legacy tokens.

## Per-user settings and admin controls

- **Settings → Telegram** (all users): **Connect Telegram**, **Unlink
  Telegram**, opt-in toggle, and **Send test message** (`POST /telegram/link`,
  `PATCH /auth/me`, `POST /notifications/test`). There is no editable chat-id
  field; the chat id is read-only and is set only by completing the link flow.
  Connect opens the bot from the API's `deep_link` with `opener` cleared; when
  the popup is blocked the deep link is shown as a fallback. The helper copy
  uses `bot_username` from the link response.
- **Settings → Users** (admins only): list local users with login, display name,
  role, active state, created/last login, and Telegram enabled; toggle
  enable/disable. Admins cannot disable themselves. The list never renders
  tokens or other users' chat ids.
- **Global scan** is admin-only: the “Scan for new drops” action is hidden for
  non-admins, and the API returns `403` if called directly.
- **Profile**: local account (login, display name, role), Twitch connection and
  sync health (`reconnect_required`, last sync/error), reconnect with a code,
  sign out, and disconnect. The URL-paste reconnect stays under **Advanced /
  desktop**. Disconnect clears that user's Twitch data but keeps the account.
- Copy that claimed “there are no local user accounts” is gone. The UI says the
  Twitch token is stored on this server for that user's account.

## Design system

**Direction:** solid Twitch-violet UI with high-contrast, readable dark surfaces.
Explicitly no gradients, glows, backdrop blur, or pill-shaped components.
Borders, spacing, and a larger type scale carry the hierarchy.

### Tokens (`:root` in `index.css`)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0e1013` | page/rail background |
| `--surface` | `#161a1f` | cards/panels |
| `--surface-2` | `#1c2128` | raised/hover |
| `--surface-3` | `#242a33` | tracks/inputs |
| `--border` / `--border-strong` | `#303740` / `#48515d` | hairlines |
| `--text` / `--text-strong` | `#eceef2` / `#ffffff` | copy |
| `--muted` / `--muted-2` | `#b6bdc9` / `#949cab` | secondary/labels |
| `--accent` | `#9146ff` | primary actions/active nav/progress |
| `--accent-strong` | `#a970ff` | hover/icons |
| `--accent-soft` | `#c9b3ff` | accent text on dark |
| `--accent-ink` | `#ffffff` | text on violet |
| `--success` / `--warning` / `--danger` / `--live` | `#7fd396` / `#f0b45c` / `#ff8b80` / `#7fd396` | states |
| `--font-sans` | system sans | body, headings, labels |
| `--font-display` | alias of `--font-sans` (700) | page titles/brand |
| `--font-mono` | system mono | numbers and technical values only |
| `--radius` / `--radius-sm` | 6px / 4px | cards/buttons |
| `--sidebar-width` | 264px | desktop rail |

### Component rules

- Body text is **15px** with 1.6 line-height; nav is 14px; page titles are
  `1.85rem`. Avoid micro-type: labels are sentence case at 12–13px, with mono
  reserved for numeric/technical data.
- Badges and chips are rectangular (3px radius), sentence case, sans-serif.
- Buttons are solid rectangles; primary is Twitch violet with white text.
- Overview quick actions use a two-column grid of equal-width buttons with
  centered icon + label; one column at ≤640px.
- Cards/panels use 1px borders and 20–22px padding; no shadows.
- Progress bars are 8px, square, solid violet/green/gray.
- The brand mark, favicon, empty-state icon, connect icon, and avatars are
  **circular**. The favicon is a violet circle with a white gift glyph.
- Icons are a **custom filled/geometric set** in `components/ui/Icon.tsx` (nav
  icons are silhouettes; utilities use square-capped strokes). Do not swap in a
  generic outline icon library.
- Headings use the sans display face; data uses mono with tabular numbers.
- Action labels state both the verb and the object, and avoid bare “Scan now” or
  “Refresh”: use “Scan for new drops”, “Sync drop progress”, “Send test message”,
  “Start watching”, “Open stream on Twitch”. Loading labels use the same verb
  (“Scanning…”, “Syncing…”, “Sending…”).

## Layout / responsive

- Desktop: fixed 264px left sidebar; sticky topbar with page title + global
  refresh/scan actions; main content max 1480px.
- ≤900px: sidebar becomes a horizontally scrollable tab bar under the topbar.
- ≤640px: compact topbar (brand + title + icon actions), 2-column stat grid,
  single-column cards, hidden button labels, full-width search/add-game row.
  Navigation moves behind a burger button; the menu opens a vertical tab panel
  and closes on navigation or `Escape`. Dashboard panels use a
  `minmax(0, 1fr)` track and `min-width: 0` grid items so long section headings
  and action buttons cannot clip the Overview panels.
- Focus states use a 2px violet outline; skip link, aria labels, `aria-live`
  toast, and keyboard-navigable tabs are preserved.
- Horizontal overflow is clipped at the page level (`html`/`body`
  `overflow-x: clip`); the 641–900px tab bar scrolls, and ≤640px uses the burger
  menu.

## Game tracking

Settings → Games keeps the current user's selected-game whitelist. Besides
picking catalog games, the **“Track a game by name”** input accepts any name
(case-insensitive) and adds it to that user's selection. Saving calls `PUT
/games`; the backend creates a `Game` row if it does not exist, so a game can be
tracked before it has a campaign. The scan then alerts that user when a campaign
for the game becomes active. Changes are local until **Save selection** is
clicked. Other users' selections are unaffected.

## Focused watcher

The Watch queue page starts with a **Focus watcher** panel. Focused mode keeps
exactly one live target selected from the current user's queue:

- **Enable focused mode** auto-picks that user's most urgent live campaign. The
  panel shows the focused channel, campaign, remaining watch minutes, and reason.
- **Next live** dispatches the watcher to another live stream (the current one is
  excluded). **Focus** on any candidate in the list changes the target manually.
- The backend worker re-checks every `WATCHER_POLL_SECONDS`. If the focused live
  goes offline while the campaign is still open, the panel switches to
  **Live offline** and one Telegram notification is sent to that user. If the
  campaign completes, the watcher sends a completion notification and turns
  focused mode off. The watcher does not auto-move and has no timer handoff.
- **Stop watcher** clears the focus. The focus panel is monitor-only; it links
  to the stream but does not track a timer. Each user has their own focus; one
  user's focus never appears in another's panel.

## Completed campaigns

Completion is persisted by the backend from Twitch `earnedDropRewards`, so it
survives a campaign leaving `dropCampaignsInProgress`. Completed campaigns sort
after unfinished campaigns and get a green **Completed** badge/border on:

- **Campaigns** — uses `Campaign.completed` from the API. The **Completed** badge
  replaces the catalog status, so a finished campaign no longer shows “Active”.
- **Progress** — completed campaigns appended from the ledger render with every
  drop claimed.
- **Overview** — completed entries appear last in “Campaign progress” and show
  “All drops claimed”.

## Start watching

Every campaign row in the Watch queue has a **Start watching** button. It:

1. opens the real Twitch stream in a new tab, and
2. dispatches the current user's focused watcher to that streamer/campaign via
   `POST /watcher/focus` (`strategy: "manual"`).

There is no local timer, elapsed-time display, or persisted watch session. The
focus panel shows the selected target and its offline/completion alerts; clicking
**Start watching** on another stream replaces that user's focus (still one
watcher per user).

## Live list limits

Both `Watch queue` and `Streams` group cards by game and show at most **5 streams
per game** by default. The `Per game` selector changes the cap to 5, 10, 20, or
All. Limiting happens client-side after filtering, so search still sees every
loaded stream. Group order follows the original sorted order (urgency for the
watch queue, viewers for Streams).

## Build / dev

```bash
npm install
npm run dev      # :5173, proxies /api to :8000
npm run build    # tsc --noEmit && vite build -> dist/
```

Production: `frontend/Dockerfile` uses `npm ci`, builds with `npm run build`,
then nginx serves `/usr/share/nginx/html` with gzip, immutable `/assets/*`,
no-cache `index.html`, and `/api/` proxy to `api:8000` (HTTP/1.1 keepalive). No
API token is baked into the bundle; auth is the session cookie. The compose
frontend binds `127.0.0.1:8282`; nginx adds CSP, HSTS, nosniff, frame-deny,
referrer and permissions headers, and forwards the inbound `X-Forwarded-Proto`
(falling back to `$scheme`). There is no shared basic-auth prompt.

## Adding a page/tab

1. Add a `TabId` and metadata to `lib/tabs.ts` (label/title/subtitle/icon).
2. Add the page under `pages/` and a case in `App.tsx`.
3. Add hooks/client/types for any new API.
4. Reuse `PageHeader`, `StatCard`, `Badge`, `EmptyState`, `Icon`.
5. Style only with tokens; no gradients/glows/pills.
6. Build, update [FRONTEND.md](FRONTEND.md), [STATUS.md](STATUS.md),
   [CHANGELOG.md](CHANGELOG.md).

## Visual verification

A temporary Playwright Chromium can screenshot the built app:

```bash
npx playwright install chromium
node shots.js   # navigate #/overview, #/campaigns, ... and full-page screenshot
```

Screenshots are for local review only; do not commit them.
