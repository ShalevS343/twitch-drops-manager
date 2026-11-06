# Frontend

React 18 + TypeScript + Vite + TanStack Query. Served by nginx in production at
port **8282**. No router dependency; tabs are hash routes.

## Structure

```
frontend/src/
  App.tsx                    shell: sidebar, topbar, tabs, toasts
  api/
    client.ts                fetch wrapper, optional X-API-Token
    types.ts                 contracts mirrored from backend schemas
  components/
    CampaignCard.tsx
    ProgressCard.tsx
    StreamCard.tsx
    WatchFocusPanel.tsx     single focused watcher, dispatch/next/stop
    WatchQueueCard.tsx
    WatchSessionPanel.tsx    active manual session, timer, next-up handoff
    TwitchConnect.tsx        reusable authorize/paste flow + hook
    GameSelector.tsx
    ui/                      Avatar, Badge, EmptyState, Icon, PageHeader,
                             PerGameSelect, Spinner, StatCard, TabNav
  hooks/
    useApi.ts                TanStack Query hooks + query result types
    useTab.ts                hash routing with canonicalization
    useWatchSession.ts       localStorage-backed manual watch timer
  lib/
    campaigns.ts             phase/percent helpers
    format.ts                date/time/remaining formatters
    streamGroups.ts          per-game limiting/grouping helpers
    tabs.ts                  tab ids + metadata
    watchQueue.ts            campaign-level "next up" suggestions
  pages/
    OverviewPage.tsx
    CampaignsPage.tsx
    ProgressPage.tsx
    WatchQueuePage.tsx
    StreamsPage.tsx
    SettingsPage.tsx
    ProfilePage.tsx
  index.css                  design system + all component styles
  main.tsx                   QueryClientProvider
```

## Tabs

Hash routes, default `#/overview`; invalid hashes are normalized:

| Route | Page | Purpose |
|---|---|---|
| `#/overview` | Overview | Stats, needs attention, queue preview, campaign progress |
| `#/campaigns` | Campaigns | Catalog with search/game/status filters |
| `#/progress` | Progress | Personal drop progress and ready-to-claim status |
| `#/watch-queue` | Watch queue | Urgency-sorted eligible streams, grouped by game, top 5 per game by default |
| `#/streams` | Streams | All matched live streams, filtered/grouped, top 5 per game by default |
| `#/settings` | Settings | Games (including track-by-name), actions, Twitch connection, system info |
| `#/profile` | Profile | Twitch account/profile, reconnect/disconnect |

`useTab` uses `window.location.hash` + `hashchange` and `history.replaceState` to
canonicalize. The skip link preserves the active tab (does not change the hash).

## Data fetching

TanStack Query; all requests go through `api/client.ts`:

- `useStatus()` — 30s
- `useTwitchStatus()` — 60s
- `useCampaigns()`, `useStreams()`, `useGames()` — on demand/shared
- `useProgress()` — 60s
- `useWatchQueue()` — 30s
- `useWatcher()` — 15s
- Mutations: save games, scan, refresh progress, test Telegram, watcher
  enable/focus/next/stop, Twitch connect, disconnect.

Invalidation: scan refreshes all queries; game save refreshes games/campaigns/
status; progress refresh refreshes progress/watch queue/twitch/status; logout
refreshes everything. Saving a game name that is not cached yet is allowed; the
response/next query reflects the newly created tracked row.

## Twitch connection flow

1. Profile/Settings/Progress render the reusable `TwitchConnect` flow.
2. `useTwitchConnect().start()` fetches `GET /twitch/connect`, opens the authorize
   URL in a new tab, and shows the paste box.
3. The user approves on Twitch, copies the full `twitch.tv/#access_token=...` URL,
   pastes it, and submits.
4. `POST /twitch/connect` stores the token, fetches/stores the profile, and runs an
   initial progress sync.
5. The UI invalidates all queries; the connection chip/profile update.

Fallbacks: initials avatar when the image fails; display name falls back to login;
missing dates render `Unknown`; token expiry can be absent for legacy tokens.

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
  “Start watch timer”, “Open stream on Twitch”. Loading labels use the same verb
  (“Scanning…”, “Syncing…”, “Sending…”).

## Layout / responsive

- Desktop: fixed 264px left sidebar; sticky topbar with page title + global
  refresh/scan actions; main content max 1480px.
- ≤900px: sidebar becomes a horizontally scrollable tab bar under the topbar.
- ≤640px: compact topbar (brand + title + icon actions), 2-column stat grid,
  single-column cards, hidden button labels, full-width search/add-game row.
- Focus states use a 2px violet outline; skip link, aria labels, `aria-live`
  toast, and keyboard-navigable tabs are preserved.
- Horizontal overflow is clipped at the page level (`html`/`body`
  `overflow-x: clip`); the mobile tab bar scrolls inside its own container.

## Game tracking

Settings → Games keeps the selected-game whitelist. Besides picking catalog games,
the **“Track a game by name”** input accepts any name (case-insensitive) and adds
it to the selection. Saving calls `PUT /games`; the backend creates a `Game` row
if it does not exist, so a game can be tracked before it has a campaign. The scan
then alerts when a campaign for that game becomes active. Changes are local until
**Save selection** is clicked.

## Focused watcher

The Watch queue page starts with a **Focus watcher** panel. Focused mode keeps
exactly one live target selected from the queue:

- **Enable focused mode** auto-picks the most urgent live campaign. The panel
  shows the focused channel, campaign, remaining watch minutes, and reason.
- **Next live** dispatches the watcher to another live stream (the current one is
  excluded). **Focus** on any candidate in the list changes the target manually.
- The backend worker re-checks the queue every `WATCHER_POLL_SECONDS`; if the
  focused live goes offline or its campaign runs out of time, the focus moves to
  the next live and the panel shows the new target. **Stop watcher** clears it.
- **Start manual session** hands the focused target to the existing local timer
  and opens the real stream. The watcher never auto-starts a session.
- The watcher is a focus pointer only. It does not play, control, or simulate
  viewing and sends no watch heartbeats.

The watcher and the manual session are independent: the watcher can move to a new
live while the timer is still on the previous one, so the UI requires an explicit
**Start manual session** click to follow it.

## Manual watch sessions

The Watch queue can start one **local** session for a chosen stream/campaign pair.
It opens the real Twitch stream in a new tab and records elapsed time in
`localStorage` under `tdm.watch-session.v1`; refreshing the page keeps the timer.
Only one session can exist at a time.

- The timer can be paused/resumed and stopped. It survives navigation and is
  synced across tabs through the `storage` event.
- `targetMinutes` comes from the campaign’s remaining watch time. When elapsed
  time reaches the target, the panel shows **Target reached** plus up to three
  campaign-level “Next up” suggestions (most urgent campaign first, best live
  stream per campaign). Switching is an explicit click — nothing auto-plays or
  auto-advances.
- The panel never controls Twitch playback, sends watch heartbeats, or simulates
  viewing. This is a manual convenience only; the read-only product boundary
  still applies.
- Session data is local to the browser and is not persisted to the backend.

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

Production: `frontend/Dockerfile` builds with `npm run build`, then nginx serves
`/usr/share/nginx/html` with gzip, immutable `/assets/*`, no-cache `index.html`,
and `/api/` proxy to `api:8000` (HTTP/1.1 keepalive).

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
