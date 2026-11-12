import { useState } from 'react'

import { TwitchConnect, useTwitchConnect } from '../components/TwitchConnect'
import { Avatar } from '../components/ui/Avatar'
import { Badge } from '../components/ui/Badge'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { useAuth } from '../auth/AuthContext'
import { useTwitchDisconnect, type TwitchStatusQuery } from '../hooks/useApi'
import { formatDateTime } from '../lib/format'
import { safeExternalUrl } from '../lib/url'

interface Props {
  twitch: TwitchStatusQuery
}

export function ProfilePage({ twitch }: Props) {
  const { user, isAdmin, telegramBotConfigured, logout, refresh } = useAuth()
  const connect = useTwitchConnect({ onConnected: refresh })
  const disconnect = useTwitchDisconnect()

  const [signingOut, setSigningOut] = useState(false)
  const [signOutError, setSignOutError] = useState<string | null>(null)

  if (!user) return null

  const data = twitch.data
  const twitchConnected = data?.connected === true
  const displayName = user.display_name || user.login || 'Twitch user'
  const twitchProfileUrl = safeExternalUrl(
    `https://www.twitch.tv/${encodeURIComponent(user.login)}`,
  )
  const telegramChatId = user.telegram_chat_id?.trim() ?? ''
  const telegramReady =
    telegramBotConfigured && user.telegram_enabled && Boolean(telegramChatId)
  const tokenExpired = Boolean(
    data?.expires_at && new Date(data.expires_at).getTime() < Date.now(),
  )
  const reconnectRequired = data?.reconnect_required === true || tokenExpired

  async function handleSignOut() {
    setSigningOut(true)
    setSignOutError(null)
    try {
      await logout()
    } catch (err) {
      setSignOutError(err instanceof Error ? err.message : 'Could not sign out')
      setSigningOut(false)
    }
  }

  return (
    <div className="page">
      <section className="panel profile-card" aria-labelledby="profile-account">
        <div className="profile-hero">
          <Avatar
            name={displayName}
            src={user.profile_image_url || data?.profile_image_url}
            size="xl"
            className="profile-avatar"
          />
          <div className="profile-identity">
            <div className="badge-row">
              <Badge tone={isAdmin ? 'accent' : 'neutral'}>
                <Icon name={isAdmin ? 'sparkles' : 'user'} size={12} />
                {isAdmin ? 'Admin' : 'User'}
              </Badge>
              <Badge tone={telegramReady ? 'success' : 'muted'} dot>
                {telegramReady ? 'Telegram alerts on' : 'Telegram alerts off'}
              </Badge>
              <Badge tone={twitchConnected ? 'success' : 'warning'} dot>
                {twitchConnected
                  ? reconnectRequired
                    ? 'Twitch reconnect needed'
                    : 'Twitch connected'
                  : 'Twitch not connected'}
              </Badge>
            </div>
            <h2 id="profile-account">{displayName}</h2>
            <p className="profile-login">@{user.login || 'unknown'}</p>
          </div>
          <div className="profile-actions">
            {twitchConnected && twitchProfileUrl && (
              <a
                className="btn btn-primary"
                href={twitchProfileUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Icon name="external" size={16} />
                Open Twitch profile
              </a>
            )}
            <button
              className="btn btn-secondary"
              onClick={connect.start}
              disabled={connect.starting}
            >
              <Icon name="twitch" size={16} />
              {connect.starting
                ? 'Starting…'
                : twitchConnected
                  ? 'Reconnect Twitch'
                  : 'Connect Twitch'}
            </button>
            <button
              className="btn btn-secondary"
              onClick={handleSignOut}
              disabled={signingOut}
            >
              <Icon name="logout" size={16} />
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        </div>

        {signOutError && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{signOutError}</span>
          </p>
        )}

        <dl className="kv-grid profile-facts">
          <div className="kv">
            <dt>Local account ID</dt>
            <dd>{user.id}</dd>
          </div>
          <div className="kv">
            <dt>Twitch login</dt>
            <dd>{user.login ? `@${user.login}` : 'Not provided'}</dd>
          </div>
          <div className="kv">
            <dt>Role</dt>
            <dd>{isAdmin ? 'Admin' : 'User'}</dd>
          </div>
          <div className="kv">
            <dt>Telegram chat ID</dt>
            <dd>{telegramChatId || 'Not set'}</dd>
          </div>
          <div className="kv">
            <dt>Telegram alerts</dt>
            <dd>
              <Badge tone={telegramReady ? 'success' : 'muted'} dot>
                {user.telegram_enabled ? 'Enabled' : 'Disabled'}
              </Badge>
            </dd>
          </div>
          <div className="kv">
            <dt>Bot configured</dt>
            <dd>
              <Badge tone={telegramBotConfigured ? 'success' : 'warning'} dot>
                {telegramBotConfigured ? 'Yes' : 'No'}
              </Badge>
            </dd>
          </div>
        </dl>
      </section>

      <section className="panel profile-card" aria-labelledby="profile-twitch">
        <div className="section-head">
          <div>
            <h2 id="profile-twitch">
              <Icon name="twitch" size={18} />
              Twitch connection
            </h2>
            <p>Your Twitch token is stored on this server for your account.</p>
          </div>
          {twitch.isLoading ? (
            <Badge tone="muted">Checking…</Badge>
          ) : (
            <Badge tone={twitchConnected ? 'success' : 'warning'} dot>
              {twitchConnected
                ? reconnectRequired
                  ? 'Reconnect required'
                  : 'Connected'
                : 'Not connected'}
            </Badge>
          )}
        </div>

        {twitch.isLoading && <LoadingState label="Loading Twitch connection…" />}

        {twitch.error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{twitch.error.message}</span>
          </p>
        )}

        {!twitch.isLoading && twitchConnected && (
          <>
            <div className="settings-status-row">
              <Avatar
                name={data?.display_name || data?.login}
                src={data?.profile_image_url}
                size="md"
              />
              <div className="settings-status-copy">
                <strong>{data?.display_name || data?.login || 'Twitch user'}</strong>
                <span className="muted small">
                  @{data?.login || 'unknown'} · Token expires{' '}
                  {formatDateTime(data?.expires_at)}
                </span>
              </div>
              <div className="inline-actions">
                <button
                  className="btn btn-secondary"
                  onClick={connect.start}
                  disabled={connect.starting}
                >
                  <Icon name="twitch" size={16} />
                  {connect.starting ? 'Starting…' : 'Reconnect Twitch'}
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => disconnect.mutate()}
                  disabled={disconnect.isPending}
                >
                  <Icon name="logout" size={16} />
                  {disconnect.isPending ? 'Disconnecting…' : 'Disconnect Twitch'}
                </button>
              </div>
            </div>

            {reconnectRequired && (
              <p className="alert alert-warning" role="status">
                <Icon name="alert" size={16} />
                <span>
                  Twitch needs this connection refreshed before progress can sync.
                  Use <strong>Reconnect Twitch</strong>.
                </span>
              </p>
            )}

            {data?.last_error && (
              <p className="alert alert-danger" role="alert">
                <Icon name="alert" size={16} />
                <span>{data.last_error}</span>
              </p>
            )}

            <dl className="kv-grid profile-facts">
              <div className="kv">
                <dt>Twitch user ID</dt>
                <dd>{data?.user_id || 'Not provided'}</dd>
              </div>
              <div className="kv">
                <dt>Connected since</dt>
                <dd>{formatDateTime(data?.connected_at)}</dd>
              </div>
              <div className="kv">
                <dt>Last synced</dt>
                <dd>{formatDateTime(data?.last_synced_at)}</dd>
              </div>
              <div className="kv">
                <dt>Connection status</dt>
                <dd>
                  <Badge tone={reconnectRequired ? 'warning' : 'success'} dot>
                    {reconnectRequired ? 'Expired — reconnect' : 'Active'}
                  </Badge>
                </dd>
              </div>
            </dl>
          </>
        )}

        {!twitch.isLoading && !twitchConnected && (
          <div className="settings-status-row">
            <span className="connect-hero-icon connect-hero-icon-sm" aria-hidden="true">
              <Icon name="twitch" size={20} />
            </span>
            <div className="settings-status-copy">
              <strong>No Twitch account connected</strong>
              <span className="muted small">
                Connect to enable drop progress, watch queue, and ready-to-claim
                alerts.
              </span>
            </div>
            <div className="inline-actions">
              <button
                className="btn btn-primary"
                onClick={connect.start}
                disabled={connect.starting}
              >
                <Icon name="twitch" size={16} />
                {connect.starting ? 'Starting…' : 'Connect Twitch'}
              </button>
            </div>
          </div>
        )}

        {disconnect.error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{disconnect.error.message}</span>
          </p>
        )}

        <TwitchConnect connect={connect} />
      </section>
    </div>
  )
}
