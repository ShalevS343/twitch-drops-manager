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
    WatchQueueCard.tsx
    TwitchConnect.tsx        reusable authorize/paste flow + hook
    GameSelector.tsx
    ui/                      Avatar, Badge, EmptyState, Icon, PageHeader,
                             Spinner, StatCard, TabNav
  hooks/
    useApi.ts                TanStack Query hooks + query result types
    useTab.ts                hash routing with canonicalization
  lib/
    campaigns.ts             phase/percent helpers
    format.ts                date/time/ETA formatters
    tabs.ts                  tab ids + metadata
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
| `#/progress` | Progress | Personal drop progress, ETA, ready-to-claim |
| `#/watch-queue` | Watch queue | Urgency-sorted eligible live streams |
| `#/streams` | Streams | All live matched streams with filters |
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
- Mutations: save games, scan, refresh progress, test Telegram, Twitch connect,
  disconnect.

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

## Layout / responsive

- Desktop: fixed 264px left sidebar; sticky topbar with page title + global
  refresh/scan actions; main content max 1480px.
- ≤900px: sidebar becomes a horizontally scrollable tab bar under the topbar.
- ≤640px: compact topbar (brand + title + icon actions), 2-column stat grid,
  single-column cards, hidden button labels, full-width search/add-game row.
- Focus states use a 2px violet outline; skip link, aria labels, `aria-live`
  toast, and keyboard-navigable tabs are preserved.

## Game tracking

Settings → Games keeps the selected-game whitelist. Besides picking catalog games,
the **“Track a game by name”** input accepts any name (case-insensitive) and adds
it to the selection. Saving calls `PUT /games`; the backend creates a `Game` row
if it does not exist, so a game can be tracked before it has a campaign. The scan
then alerts when a campaign for that game becomes active. Changes are local until
**Save selection** is clicked.

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
