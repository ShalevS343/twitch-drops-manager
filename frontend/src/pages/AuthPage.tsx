import { useAuth } from '../auth/AuthContext'
import { TwitchConnect, useTwitchConnect } from '../components/TwitchConnect'
import { Icon } from '../components/ui/Icon'

export function AuthPage() {
  const { login, registration, notice, clearNotice, error } = useAuth()

  const connect = useTwitchConnect({
    mode: 'login',
    inviteRequired: registration.invite_required,
    authenticate: login,
    onConnected: clearNotice,
  })

  const closed = !registration.open

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
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{error}</span>
          </p>
        )}

        {closed && (
          <p className="notice">
            <Icon name="alert" size={15} />
            <span>
              New registrations are closed. If you already have an account, sign in
              with Twitch below. Otherwise ask the admin for access.
            </span>
          </p>
        )}

        <div className="auth-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={connect.start}
            disabled={connect.starting}
          >
            <Icon name="twitch" size={16} />
            {connect.starting
              ? 'Opening Twitch…'
              : connect.connect
                ? 'Reopen Twitch authorization'
                : 'Continue with Twitch'}
          </button>
          {registration.invite_required && (
            <span className="muted small">An invite code is required for new accounts.</span>
          )}
        </div>

        <TwitchConnect connect={connect} />

        <p className="muted small auth-foot">
          The Twitch token is stored on this server for your account. Sign-in uses a
          cookie-based session, not a browser token.
        </p>
      </main>
    </div>
  )
}
