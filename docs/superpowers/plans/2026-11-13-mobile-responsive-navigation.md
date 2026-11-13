# Mobile Responsiveness + Off-canvas Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove phone-width clipping on every dashboard page and turn the ≤640px burger menu into a left off-canvas drawer that overlays the page.

**Architecture:** Keep the existing React shell, hash tabs, token CSS and `TabNav`. Add drawer state behavior (scrim, focus return, focus trap, scroll lock) to `App.tsx`; do the visual work with media queries in `src/index.css`. Fix intrinsic-width blowouts at the source (grid tracks, nowrap list meta) instead of hiding overflow.

**Tech Stack:** React 18, TypeScript strict, Vite, plain CSS tokens. Verification with the project build plus a temporary Playwright audit script outside the repo.

**Spec:** `docs/superpowers/specs/2026-11-13-mobile-responsive-navigation-design.md`

## Global Constraints

- No new runtime/dev dependencies.
- No gradients, glows, backdrop blur or pill shapes.
- No backend, API, auth or schema changes.
- Desktop ≥901px and tablet 641–900px must look and behave as before.
- The drawer must be keyboard operable and must return focus to the burger.
- Mobile targets: 320, 360, 390, 414 px wide; tablet check at 768 px.
- `npm run build` must pass before every commit.

## Review Focus

- A 320px viewport with the Settings page open must not clip any section.
- Long account/game/campaign names must wrap or ellipsize, never widen the page.
- The open drawer must cover the page, lock background scroll, and close on
  scrim/Escape/navigation.
- Closed drawer links must not be tabbable.
- A signed-out phone user must still see a usable auth card.

---

### Task 1: Reproduce and pin the failures

**Files:**
- Create (outside repo): `/tmp/opencode/tdm-audit.mjs`
- Test: same script, run against `npm run dev`

**Interfaces:**
- Produces: an audit command that prints `OVERFLOW` per tab/width and exits
  non-zero on overflow; drawer checks for open/close/focus/scroll lock.

- [ ] **Step 1: Write the audit script**

It must mock `/api/v1/**` (auth, status, twitch status, games, campaigns,
streams, progress, watch-queue, watcher, admin users), loop widths
`320,360,390,414,768`, visit every tab, and assert:
`document.documentElement.scrollWidth <= clientWidth + 1` and the same for
`body`. At 390 it also opens the burger and asserts the drawer is visible, the
scrim exists, `body` scroll is locked, activeElement is inside the drawer, and
Escape restores focus to the burger.

- [ ] **Step 2: Run it and confirm the baseline fails**

Run: `cd frontend && npm run dev -- --host 127.0.0.1` then
`node /tmp/opencode/tdm-audit.mjs`
Expected: `settings` at 320/360/390/414 reports `OVERFLOW` (body ~680px);
drawer assertions fail because the panel is inline.

- [ ] **Step 3: Commit nothing**

The audit harness is temporary and must stay out of the repo.

---

### Task 2: Off-canvas drawer

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css` (sidebar, topbar, responsive blocks)
- Test: `/tmp/opencode/tdm-audit.mjs`

**Interfaces:**
- Consumes: existing `mobileNavOpen`, `setMobileNavOpen`, `tab`, `navigate`.
- Produces: `.nav-scrim` element; `.sidebar.is-open`; drawer close button with
  `aria-label="Close navigation"`.

- [ ] **Step 1: Add drawer behavior to `App.tsx`**

Add refs for the burger and drawer, a scrim button, a close button in the brand
row, body scroll lock on open, Escape close, focus-on-open to the close button,
focus return to the burger on close, and a Tab/Shift+Tab focus trap limited to
the open drawer. Keep the existing `tab` change effect, and restore focus there
too. Set `role="dialog"`/`aria-modal="true"` only while open (mobile). Render the
scrim before the aside with `className="nav-scrim"`, `aria-hidden="true"`,
`tabIndex={-1}` and an `onClick` close handler.

- [ ] **Step 2: Add drawer CSS**

At ≤640px: `.sidebar` fixed, left, `width: min(84vw, 300px)`, full height,
column layout, `translateX(-100%)`, `visibility: hidden`, `overflow-y: auto`,
z-index 60. `.sidebar.is-open`: `translateX(0)`, visible. `.nav-scrim`: fixed
inset 0, `rgba(0,0,0,0.62)`, z-index 50, no border/padding. Show the close button
only ≤640px. Add `prefers-reduced-motion` to remove the transform transition.
Do not alter the 641–900px horizontal tab strip.

- [ ] **Step 3: Run the audit**

Run: `node /tmp/opencode/tdm-audit.mjs --drawer-only`
Expected: drawer checks pass; Settings overflow still fails (next task).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/index.css
git commit -m "feat(ui): add off-canvas mobile navigation drawer"
```

---

### Task 3: Settings and list overflow

**Files:**
- Modify: `frontend/src/index.css`
- Test: `/tmp/opencode/tdm-audit.mjs`

- [ ] **Step 1: Let the settings track shrink**

In the ≤1180px block, change `.settings-grid` to
`grid-template-columns: minmax(0, 1fr)` and add
`.settings-section { min-width: 0; }`.

- [ ] **Step 2: Make list rows wrap on phones**

At ≤640px add rules scoped to `.list-item` inside `.settings-section` and the
existing overview lists: `flex-wrap: wrap`, `.list-item-main { flex: 1 1 140px }`,
`.list-item-title, .list-item-meta { white-space: normal; overflow-wrap:
anywhere }`, `.list-item-actions { width: 100%; justify-content: flex-end;
flex-wrap: wrap }`. Keep the desktop single-line ellipsis behavior above 640px.

- [ ] **Step 3: Run the audit**

Run: `node /tmp/opencode/tdm-audit.mjs`
Expected: Settings and all other tabs no longer report `OVERFLOW` at any width.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css
git commit -m "fix(ui): stop settings and list rows overflowing on phones"
```

---

### Task 4: Cross-page phone polish

**Files:**
- Modify: `frontend/src/index.css`
- Test: `/tmp/opencode/tdm-audit.mjs`

- [ ] **Step 1: Stack the Overview connect callout**

At ≤480px: `.callout { flex-direction: column; align-items: flex-start; }` and
`.callout .btn { width: 100%; }`.

- [ ] **Step 2: Harden long/edge content**

Add `overflow-wrap: anywhere` and `min-width: 0` where needed: `code`,
`.kv dd`, `.chip`, `.section-head > div`, `.settings-status-copy`. At ≤480px
stack `.kv` to `flex-direction: column`, left-align `.kv dd`, and let `.btn`
wrap (`white-space: normal`). Add `flex-wrap: wrap` to `.form-actions`.

- [ ] **Step 3: Use the width on small buttons**

At ≤640px make `.action-card .btn`, `.form-actions .btn`,
`.add-game-row .btn` and `.whitelist-footer .btn` full width; cap the topbar
connection name with `max-width: 96px`, ellipsis and nowrap; reduce the mobile
topbar column gap to 12px.

- [ ] **Step 4: Re-run audit and review screenshots**

Run: `node /tmp/opencode/tdm-audit.mjs` and `WIDTHS=320,390 node
/tmp/opencode/tdm-shots.js`
Expected: no overflow; screenshots of Overview, Settings, Auth, Profile readable.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/index.css
git commit -m "fix(ui): polish phone layouts across pages"
```

---

### Task 5: Verify, document, merge, deploy

**Files:**
- Modify: `docs/FRONTEND.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHANGELOG.md`
- Test: build + audit + live checks

- [ ] **Step 1: Run the full verification**

```bash
cd frontend && npm run build
cd ../backend && PYTHONPATH=$PWD pytest -q && ruff check app tests
```

Backend has no changes but the documented floor is 307 tests; record the result.
(`pytest` may need the venv; if unavailable, state that the build-only frontend
change was verified and the backend suite was not run.)

- [ ] **Step 2: Update docs**

`FRONTEND.md`: drawer behavior, new breakpoints, list/callout rules.
`STATUS.md`: current state, validation, deploy note.
`CHANGELOG.md`: dated mobile responsiveness entry.

- [ ] **Step 3: Commit docs**

```bash
git add docs/FRONTEND.md docs/STATUS.md docs/CHANGELOG.md
git commit -m "docs: record mobile drawer and responsive fixes"
```

- [ ] **Step 4: Merge to main and push**

```bash
git checkout main && git pull --ff-only
git merge --no-ff feat/mobile-responsive-nav
git push origin main
```

- [ ] **Step 5: Back up and redeploy the Portainer stack**

Back up `/data/drops.db` using the WAL-safe SQLite backup first, then pull and
redeploy stack `twitch-drops-manager` through the Portainer API (token at
`/home/server/.portainer-token`). Verify containers are healthy and
`/api/v1/health` returns OK over the public URL.

- [ ] **Step 6: Verify live**

Check the public URL loads, `npm`/nginx serves the new bundle, `/api/v1/health`
is OK, and all three containers are running. Record the deployed commit in
`STATUS.md` if the deploy succeeds (follow-up docs commit only if needed).

## Self-review

- Spec coverage: drawer, Settings track, list wrap, callout, long strings,
  Auth card, all-tab audit, docs, deploy.
- No step carries more than one decision.
- No later-task type/name drift: drawer classes are `.nav-scrim`,
  `.sidebar.is-open`, and the close label is fixed above.
- Review Focus tests are owned by Task 1/3/4 and the final audit.
