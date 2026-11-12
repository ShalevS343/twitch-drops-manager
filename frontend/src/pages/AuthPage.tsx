import { useState } from 'react'

import { useAuth } from '../auth/AuthContext'
import { DeviceConnect, useDeviceConnect } from '../components/DeviceConnect'
import { TwitchConnect, useTwitchConnect } from '../components/TwitchConnect'
import { Icon } from '../components/ui/Icon'

export function AuthPage() {
  const { login, registration, notice, clearNotice, error, refresh } = useAuth()
  const [retrying, setRetrying] = useState(false)
  const closed = !registration.open && !error

  // Code login is the primary path on phones and desktop; the implicit
  // authorize/paste flow stays available under Advanced / desktop.
  const device = useDeviceConnect({
    mode: 'login',
    inviteRequired: registration.invite_required && !closed,
    onConnected: clearNotice,
  })

  const connect = useTwitchConnect({
    mode: 'login',
    inviteRequired: registration.invite_required,
    authenticate: login,
    onConnected: clearNotice,
  })

  async function handleRetry() {
    setRetrying(true)
    try {
      await refresh()
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="auth-shell">
      <main className="auth-card" aria-labelledby="auth-title">
        <div className="brand auth-brand">
          <span className="brand-mark">
            <Icon name="gift" size={20} />
          </span>
          <span className="brand-copy">
            <span className="brand-name">Drops Manager</span>
            <span className="brand-sub">Twitch dashboard</span>
          </span>
        </div>

        <div className="auth-hero">
          <span className="connect-hero-icon" aria-hidden="true">
            <Icon name="twitch" size={22} />
          </span>
          <div className="connect-hero-copy">
            <h1 id="auth-title">Sign in to Drops Manager</h1>
            <p>
              Use your Twitch account to track drop progress, watch queues, and alerts.
            </p>
          </div>
        </div>

        {notice && (
          <p className="alert alert-warning" role="status">
            <Icon name="alert" size={16} />
            <span>{notice}</span>
          </p>
        )}

        {error && (
          <div className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{error}</span>
            <button
              type="button"
              className="btn btn-secondary btn-sm auth-retry"
              onClick={handleRetry}
              disabled={retrying}
            >
              <Icon name="refresh" size={14} />
              {retrying ? 'Retrying…' : 'Retry'}
            </button>
          </div>
        )}

        {closed && (
          <p className="muted small">
            New registrations are closed. If you already have an account, sign in
            with Twitch below. Otherwise ask the admin for access.
          </p>
        )}

        <DeviceConnect connect={device} />

        <details className="advanced-connect">
          <summary>Advanced / desktop: paste a Twitch URL instead</summary>
          <div className="advanced-connect-body">
            <p className="muted small">
              Use this fallback only if the code screen is unavailable. It opens
              Twitch in a new tab and asks you to paste the redirect URL.
            </p>
            <div className="auth-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={connect.start}
                disabled={connect.starting}
              >
                <Icon name="twitch" size={16} />
                {connect.starting
                  ? 'Opening Twitch…'
                  : connect.connect
                    ? 'Reopen Twitch authorization'
                    : 'Continue with Twitch URL'}
              </button>
              {registration.invite_required && !closed && (
                <span className="muted small">
                  An invite code is required for new accounts.
                </span>
              )}
            </div>

            <TwitchConnect connect={connect} />
          </div>
        </details>

        <p className="muted small auth-foot">
          The Twitch token is stored on this server for your account. Sign-in uses a
          cookie-based session, not a browser token.
        </p>
      </main>
    </div>
  )
}
