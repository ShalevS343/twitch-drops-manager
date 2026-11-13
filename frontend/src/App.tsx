import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { CampaignsPage } from './pages/CampaignsPage'
import { OverviewPage } from './pages/OverviewPage'
import { ProfilePage } from './pages/ProfilePage'
import { ProgressPage } from './pages/ProgressPage'
import { SettingsPage } from './pages/SettingsPage'
import { StreamsPage } from './pages/StreamsPage'
import { WatchQueuePage } from './pages/WatchQueuePage'
import {
  useRefreshProgress,
  useScan,
  useStatus,
  useTwitchStatus,
} from './hooks/useApi'
import { useAuth } from './auth/AuthContext'
import { useTab } from './hooks/useTab'
import { TABS } from './lib/tabs'
import { Avatar } from './components/ui/Avatar'
import { Icon } from './components/ui/Icon'
import { PageHeader } from './components/ui/PageHeader'
import { TabNav } from './components/ui/TabNav'

interface Toast {
  tone: 'success' | 'danger'
  message: string
}

export default function App() {
  const { tab, navigate } = useTab()
  const { user, isAdmin, logout } = useAuth()
  const status = useStatus()
  const twitch = useTwitchStatus()
  const scan = useScan()
  const refresh = useRefreshProgress()

  const [toast, setToast] = useState<Toast | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [signingOut, setSigningOut] = useState(false)

  const burgerRef = useRef<HTMLButtonElement>(null)
  const drawerRef = useRef<HTMLElement>(null)
  const drawerCloseRef = useRef<HTMLButtonElement>(null)
  const drawerWasOpenRef = useRef(false)

  const closeMobileNav = () => setMobileNavOpen(false)

  useEffect(() => {
    setMobileNavOpen(false)
  }, [tab])

  // Mobile drawer: lock background scroll, move focus inside, trap Tab and
  // restore focus to the burger when it closes for any reason.
  useEffect(() => {
    if (!mobileNavOpen) {
      if (drawerWasOpenRef.current) {
        drawerWasOpenRef.current = false
        burgerRef.current?.focus()
      }
      return
    }

    drawerWasOpenRef.current = true
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusFrame = window.requestAnimationFrame(() => {
      drawerCloseRef.current?.focus()
    })

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        setMobileNavOpen(false)
        return
      }
      if (event.key !== 'Tab') return

      const items = Array.from(
        drawerRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null)

      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [mobileNavOpen])

  // If the viewport grows past the mobile breakpoint while the drawer is open,
  // close it so the desktop sidebar is not left behind a scroll lock or scrim.
  useEffect(() => {
    if (!mobileNavOpen) return

    const query = window.matchMedia('(min-width: 641px)')
    const handleChange = () => {
      if (query.matches) setMobileNavOpen(false)
    }

    handleChange()
    query.addEventListener('change', handleChange)
    return () => query.removeEventListener('change', handleChange)
  }, [mobileNavOpen])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 6000)
    return () => window.clearTimeout(timer)
  }, [toast])

  const meta = TABS.find((item) => item.id === tab) ?? TABS[0]
  const connected = twitch.data?.connected === true
  const accountName = user?.display_name || user?.login || 'Account'
  const roleLabel = isAdmin ? 'Admin' : 'Signed in'

  async function handleScan() {
    try {
      const result = await scan.mutateAsync(undefined)
      setToast({
        tone: 'success',
        message: `Scan complete — ${result.campaign_count} campaigns, ${result.stream_count} streams, ${result.notified_count} notifications.`,
      })
    } catch (err) {
      setToast({
        tone: 'danger',
        message: err instanceof Error ? err.message : 'Scan failed',
      })
    }
  }

  async function handleRefresh() {
    try {
      const result = await refresh.mutateAsync(undefined)
      if (!result.connected) {
        setToast({
          tone: 'danger',
          message: 'Twitch reconnect required before drop progress can sync.',
        })
        return
      }
      setToast({
        tone: 'success',
        message: `Synced ${result.drop_count} drops from ${result.campaign_count} campaign(s).`,
      })
    } catch (err) {
      setToast({
        tone: 'danger',
        message: err instanceof Error ? err.message : 'Could not sync drop progress',
      })
    }
  }

  async function handleLogout() {
    setSigningOut(true)
    try {
      await logout()
    } catch (err) {
      setToast({
        tone: 'danger',
        message: err instanceof Error ? err.message : 'Could not sign out',
      })
    } finally {
      setSigningOut(false)
    }
  }

  let page: ReactNode
  switch (tab) {
    case 'campaigns':
      page = <CampaignsPage />
      break
    case 'progress':
      page = <ProgressPage twitch={twitch} />
      break
    case 'watch-queue':
      page = <WatchQueuePage />
      break
    case 'streams':
      page = <StreamsPage />
      break
    case 'settings':
      page = <SettingsPage status={status} twitch={twitch} />
      break
    case 'profile':
      page = <ProfilePage twitch={twitch} />
      break
    case 'overview':
    default:
      page = <OverviewPage status={status} twitch={twitch} />
      break
  }

  return (
    <>
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault()
          document.getElementById('main-content')?.focus()
        }}
      >
        Skip to content
      </a>

      <div className="app-shell">
        <div className="main">
          <header className="topbar">
            <a
              className="mobile-brand"
              href="#/overview"
              aria-label="Twitch Drops Manager overview"
            >
              <span className="brand-mark">
                <Icon name="gift" size={18} />
              </span>
            </a>

            <PageHeader title={meta.title} description={meta.subtitle} />

            <button
              ref={burgerRef}
              type="button"
              className="btn btn-secondary mobile-menu-toggle"
              aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'}
              aria-expanded={mobileNavOpen}
              aria-controls="mobile-nav"
              onClick={() => setMobileNavOpen((open) => !open)}
            >
              <Icon name={mobileNavOpen ? 'x' : 'menu'} size={18} />
            </button>

            <div className="topbar-actions">
              <a
                className="mobile-connection"
                href="#/profile"
                aria-label={`Signed in as ${accountName}. Manage account`}
              >
                <Avatar name={accountName} src={user?.profile_image_url} size="sm" />
                <span>{accountName}</span>
                <span
                  className={`status-dot${connected ? ' online' : ''}`}
                  aria-hidden="true"
                />
              </a>

              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleRefresh}
                disabled={refresh.isPending || !connected}
                title={
                  connected
                    ? 'Sync your Twitch drop progress'
                    : 'Connect Twitch first'
                }
                aria-label="Sync drop progress from Twitch"
              >
                <Icon name="refresh" size={16} />
                <span className="btn-label">
                  {refresh.isPending ? 'Syncing…' : 'Sync drop progress'}
                </span>
              </button>

              {isAdmin && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleScan}
                  disabled={scan.isPending}
                  title="Scan campaigns and live streams, then send new alerts"
                  aria-label="Scan campaigns and live streams"
                >
                  <Icon name="scan" size={16} />
                  <span className="btn-label">
                    {scan.isPending ? 'Scanning…' : 'Scan for new drops'}
                  </span>
                </button>
              )}

              <button
                type="button"
                className="btn btn-ghost btn-icon"
                onClick={handleLogout}
                disabled={signingOut}
                aria-label="Sign out"
                title="Sign out"
              >
                <Icon name="logout" size={16} />
              </button>

              <a
                className="user-chip"
                href="#/profile"
                aria-label={`Signed in as ${accountName}. Open account settings`}
              >
                <Avatar name={accountName} src={user?.profile_image_url} size="sm" />
                <span className="user-chip-copy">
                  <span className="user-chip-name">{accountName}</span>
                  <span className="user-chip-role">{roleLabel}</span>
                </span>
              </a>
            </div>
          </header>

          {mobileNavOpen && (
            <button
              type="button"
              className="nav-scrim"
              tabIndex={-1}
              aria-hidden="true"
              onClick={closeMobileNav}
            />
          )}

          <aside
            id="mobile-nav"
            ref={drawerRef}
            className={`sidebar${mobileNavOpen ? ' is-open' : ''}`}
            role={mobileNavOpen ? 'dialog' : undefined}
            aria-modal={mobileNavOpen ? true : undefined}
            aria-label="Dashboard navigation"
          >
            <button
              ref={drawerCloseRef}
              type="button"
              className="drawer-close"
              aria-label="Close navigation"
              onClick={closeMobileNav}
            >
              <Icon name="x" size={18} />
            </button>

            <a
              className="brand"
              href="#/overview"
              aria-label="Twitch Drops Manager overview"
            >
              <span className="brand-mark">
                <Icon name="gift" size={20} />
              </span>
              <span className="brand-copy">
                <span className="brand-name">Drops Manager</span>
                <span className="brand-sub">Twitch dashboard</span>
              </span>
            </a>

            <div className="nav-section-label">Dashboard</div>
            <TabNav
              tabs={TABS}
              active={tab}
              onNavigate={(next) => {
                navigate(next)
                setMobileNavOpen(false)
              }}
            />

            <div className="sidebar-footer">
              <a
                className="connection-chip"
                href="#/profile"
                aria-label={`Signed in as ${accountName}. Manage account`}
              >
                <Avatar name={accountName} src={user?.profile_image_url} size="sm" />
                <span className="connection-copy">
                  <span className="connection-label">{accountName}</span>
                  <span className="connection-sub">
                    {roleLabel} · {connected ? 'Twitch connected' : 'Twitch not connected'}
                  </span>
                </span>
                <span
                  className={`status-dot${connected ? ' online' : ''}`}
                  aria-hidden="true"
                />
              </a>

              <button
                type="button"
                className="btn btn-ghost btn-sm sidebar-signout"
                onClick={handleLogout}
                disabled={signingOut}
              >
                <Icon name="logout" size={15} />
                {signingOut ? 'Signing out…' : 'Sign out'}
              </button>
            </div>
          </aside>

          <main id="main-content" className="content" tabIndex={-1}>
            {page}
          </main>
        </div>
      </div>

      {toast && (
        <div className="toast-stack" aria-live="polite" aria-atomic="true">
          <div className={`toast toast-${toast.tone}`} role="status">
            <Icon
              name={toast.tone === 'success' ? 'check' : 'alert'}
              size={16}
            />
            <span className="toast-message">{toast.message}</span>
            <button
              type="button"
              className="toast-close"
              onClick={() => setToast(null)}
              aria-label="Dismiss notification"
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
      )}
    </>
  )
}
