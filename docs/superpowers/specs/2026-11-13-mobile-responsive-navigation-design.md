# Mobile responsiveness + off-canvas navigation — design

Date: 2026-11-13
Status: approved-by-instruction (user asked for plan, review, build, push, deploy)

## Intent

Make every screen usable on a phone (320–430 CSS px) without clipped content,
and replace the inline burger panel with a left-side navigation drawer that
slides over the page.

## What is broken today

- **Settings is unusable on a phone.** The admin `Users` list contains a
  `white-space: nowrap` meta line inside a grid track declared `1fr`. The track's
  auto minimum grows to ~664px, so the whole `.settings-grid` becomes ~664px
  wide. `html { overflow-x: clip }` then cuts off most of every Settings section
  at the right edge (verified at 320px and 390px: body scroll width 680px).
- **Overview connect callout collapses at 320px.** The icon, copy and button
  share one row with `flex-wrap`, leaving the copy ~80px wide and the heading one
  word per line.
- **Mobile nav is an inline panel.** At ≤640px the burger toggles the sidebar
  into normal flow under the topbar. It pushes content down instead of
  overlaying it, has no scrim, and does not lock the page behind it.
- **Long strings can overflow.** Game chips, list meta, `code` values and
  key/value rows rely on desktop widths.

## Goals

1. Off-canvas drawer at ≤640px: left side, over the content, with scrim.
2. No horizontal clipping at 320, 360, 390, 414 and 768 CSS px on any page.
3. Settings, Overview, Auth and all list/detail pages remain readable and
   tappable (≥38px controls).
4. Desktop (≥901px) and tablet tab-strip (641–900px) behavior is unchanged.

## Non-goals

- No new dependencies, router, icon set, or visual redesign.
- No backend/API changes.
- No drawer at desktop/tablet widths.
- No change to auth/session behavior.

## Approaches considered

1. **Tailwind/component rewrite** — rejected: adds a dependency and conflicts
   with the documented token-based CSS system.
2. **Keep inline panel, just make Settings fit** — rejected: does not satisfy
   the requested drawer behavior.
3. **CSS off-canvas drawer + targeted mobile rules** — chosen. It reuses the
   existing `.sidebar`/`TabNav`, adds a scrim and focus/scroll management in
   `App.tsx`, and fixes the intrinsic-width bugs with a small set of media
   queries.

## Design decisions

### Drawer

- Same `<aside id="mobile-nav" class="sidebar">` element; at ≤640px it becomes
  `position: fixed; inset: 0 auto 0 0; width: min(84vw, 300px)`, full-height,
  column layout, translated off-screen with `translateX(-100%)` and
  `visibility: hidden`.
- `.is-open` restores `translateX(0)` and visibility. A short transform
  transition is used; `prefers-reduced-motion: reduce` disables it.
- A full-screen `.nav-scrim` button sits below the drawer (`z-index` 50 vs 60),
  closes on click, and is not focusable (`tabIndex={-1}`, `aria-hidden`).
- The existing burger button stays in the topbar, keeps
  `aria-expanded`/`aria-controls`, and gets `aria-label` open/close.
- Drawer has a visible close button in its brand row at ≤640px.
- On open: remember the previously focused element, focus the drawer close
  button, lock `body` scroll, and trap Tab/Shift+Tab inside the drawer.
- Escape, scrim click, close button, and navigation all close the drawer and
  restore focus to the burger. Route changes already close it; that effect is
  kept and also restores focus.
- `role="dialog"` and `aria-modal="true"` apply only while the drawer is open
  and only at mobile width; desktop keeps a plain complementary sidebar. The
  open/closed state is React state, so the attributes are conditionally applied
  on the same element.

### Responsive fixes

- `.settings-grid` uses `minmax(0, 1fr)` for its mobile track and
  `.settings-section` gets `min-width: 0`; this removes the intrinsic-width
  blowout.
- At ≤640px the admin/overview `.list-item` wraps: the main copy takes a full
  row when needed, meta lines wrap, and action groups move to their own row.
- At ≤480px the Overview `.callout` stacks vertically with a full-width action.
- Mobile rules allow `.btn` labels to wrap, make action-card/primary row
  buttons full width where they already stack, wrap form actions, and cap the
  topbar connection name with ellipsis.
- Long unbroken strings (`code`, `.kv dd`, chips, list meta) get
  `overflow-wrap: anywhere` / `min-width: 0` so they cannot push the layout.
- Key/value rows stack label over value at ≤480px for readability.

## Verification

- `npm run build` (tsc + vite) passes.
- Playwright audit at 320/360/390/414/768 px, authenticated mock, on every tab
  (overview, campaigns, progress, watch-queue, streams, settings, profile) plus
  the signed-out auth page:
  - `document.documentElement.scrollWidth <= clientWidth` and
    `body.scrollWidth <= clientWidth`.
  - no element extends more than 1px past the viewport (except intentionally
    off-canvas drawer when closed).
- Drawer interaction checks: open, scrim close, Escape close, focus moves into
  drawer and returns to burger, body scroll locked, desktop/tablet unaffected.
- Manual screenshots at 320 and 390 reviewed before deploy.

## Left to the builder

Exact spacing, the drawer width cap, transition duration, and which existing
rules are tightened rather than replaced. Keep the documented design language:
solid surfaces, no gradients/glows/backdrop blur/pills.
