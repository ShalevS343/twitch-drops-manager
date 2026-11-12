import { useEffect, useState } from 'react'
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

  useEffect(() => {
    setMobileNavOpen(false)
  }, [tab])

  useEffect(() => {
    if (!mobileNavOpen) return

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMobileNavOpen(false)
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [mobileNavOpen])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 6000)
    return () => window.clearTimeout(timer)
  }, [toast])

  const meta = TABS.find((item) => item.id === tab) ?? TABS[0]
  const connected = twitch.data?.connected === true
  const twitchName = twitch.data?.display_name || twitch.data?.login
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

          <aside
            id="mobile-nav"
            className={`sidebar${mobileNavOpen ? ' is-open' : ''}`}
          >
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
                    {roleLabel} · {connected ? twitchName || 'Twitch connected' : 'Twitch not connected'}
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
