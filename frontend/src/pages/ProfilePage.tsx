import { TwitchConnect, useTwitchConnect } from '../components/TwitchConnect'
import { Avatar } from '../components/ui/Avatar'
import { Badge } from '../components/ui/Badge'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { useTwitchLogout, type TwitchStatusQuery } from '../hooks/useApi'
import { formatDateTime } from '../lib/format'

interface Props {
  twitch: TwitchStatusQuery
}

export function ProfilePage({ twitch }: Props) {
  const connect = useTwitchConnect()
  const logout = useTwitchLogout()

  if (twitch.isLoading) {
    return <LoadingState label="Loading Twitch profile…" />
  }

  const data = twitch.data
  const connected = data?.connected === true
  const displayName = data?.display_name || data?.login || 'Twitch user'
  const login = data?.login || null
  const profileUrl = login
    ? `https://www.twitch.tv/${encodeURIComponent(login)}`
    : 'https://www.twitch.tv'
  const tokenExpired = Boolean(
    data?.expires_at && new Date(data.expires_at).getTime() < Date.now(),
  )

  return (
    <div className="page">
      {twitch.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{twitch.error.message}</span>
        </p>
      )}

      <section className="panel profile-card">
        {connected ? (
          <>
            <div className="profile-hero">
              <Avatar
                name={displayName}
                src={data?.profile_image_url}
                size="xl"
                className="profile-avatar"
              />
              <div className="profile-identity">
                <div className="badge-row">
                  <Badge tone={tokenExpired ? 'warning' : 'success'} dot>
                    {tokenExpired ? 'Token expired' : 'Connected'}
                  </Badge>
                  <Badge tone="accent">
                    <Icon name="twitch" size={12} />
                    Twitch
                  </Badge>
                </div>
                <h2>{displayName}</h2>
                <p className="profile-login">@{login || 'unknown'}</p>
              </div>
              <div className="profile-actions">
                <a
                  className="btn btn-primary"
                  href={profileUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Icon name="external" size={16} />
                  Open Twitch profile
                </a>
                <button
                  className="btn btn-secondary"
                  onClick={connect.start}
                  disabled={connect.starting}
                >
                  <Icon name="twitch" size={16} />
                  {connect.starting ? 'Starting…' : 'Reconnect'}
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => logout.mutate()}
                  disabled={logout.isPending}
                >
                  <Icon name="logout" size={16} />
                  {logout.isPending ? 'Disconnecting…' : 'Disconnect'}
                </button>
              </div>
            </div>

            <dl className="kv-grid profile-facts">
              <div className="kv">
                <dt>Display name</dt>
                <dd>{data?.display_name || 'Not provided'}</dd>
              </div>
              <div className="kv">
                <dt>Login</dt>
                <dd>{login ? `@${login}` : 'Not provided'}</dd>
              </div>
              <div className="kv">
                <dt>User ID</dt>
                <dd>{data?.user_id || 'Not provided'}</dd>
              </div>
              <div className="kv">
                <dt>Connected since</dt>
                <dd>{formatDateTime(data?.connected_at)}</dd>
              </div>
              <div className="kv">
                <dt>Token expiry</dt>
                <dd>{formatDateTime(data?.expires_at)}</dd>
              </div>
              <div className="kv">
                <dt>Connection status</dt>
                <dd>
                  <Badge tone={tokenExpired ? 'warning' : 'success'} dot>
                    {tokenExpired ? 'Expired — reconnect' : 'Active'}
                  </Badge>
                </dd>
              </div>
            </dl>

            {logout.error && (
              <p className="alert alert-danger" role="alert">
                <Icon name="alert" size={16} />
                <span>{logout.error.message}</span>
              </p>
            )}

            <TwitchConnect connect={connect} />

            <p className="notice">
              <Icon name="twitch" size={15} />
              <span>
                Profile is read directly from Twitch. This app stores only an OAuth
                token; there are no local user accounts.
              </span>
            </p>
          </>
        ) : (
          <>
            <div className="profile-hero">
              <Avatar name="Twitch" size="xl" className="profile-avatar" />
              <div className="profile-identity">
                <div className="badge-row">
                  <Badge tone="warning" dot>
                    Not connected
                  </Badge>
                </div>
                <h2>Connect your Twitch account</h2>
                <p className="profile-login">
                  Sign in to see your drop progress, ETAs, and ready-to-claim status.
                </p>
              </div>
              <div className="profile-actions">
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

            <TwitchConnect connect={connect} />

            <p className="notice">
              <Icon name="twitch" size={15} />
              <span>
                Profile is read directly from Twitch. This app stores only an OAuth
                token; there are no local user accounts.
              </span>
            </p>
          </>
        )}
      </section>
    </div>
  )
}
