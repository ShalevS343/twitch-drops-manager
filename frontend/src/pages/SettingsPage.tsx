import { GameSelector } from '../components/GameSelector'
import { TwitchConnect, useTwitchConnect } from '../components/TwitchConnect'
import { Avatar } from '../components/ui/Avatar'
import { Badge } from '../components/ui/Badge'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import {
  useGames,
  useRefreshProgress,
  useScan,
  useTestTelegram,
  useTwitchLogout,
  type StatusQuery,
  type TwitchStatusQuery,
} from '../hooks/useApi'
import { formatDateTime, formatSeconds } from '../lib/format'

interface Props {
  status: StatusQuery
  twitch: TwitchStatusQuery
}

function configuredBadge(value: boolean | undefined) {
  if (value === undefined) return <Badge tone="muted">Unknown</Badge>
  return value ? (
    <Badge tone="success" dot>
      Configured
    </Badge>
  ) : (
    <Badge tone="warning" dot>
      Missing
    </Badge>
  )
}

export function SettingsPage({ status, twitch }: Props) {
  const games = useGames()
  const scan = useScan()
  const refresh = useRefreshProgress()
  const testTelegram = useTestTelegram()
  const logout = useTwitchLogout()
  const connect = useTwitchConnect()

  const connected = twitch.data?.connected === true
  const statusData = status.data

  return (
    <div className="page settings-grid">
      <section className="panel settings-section" aria-labelledby="settings-games">
        <div className="section-head">
          <div>
            <h2 id="settings-games">
              <Icon name="gift" size={18} />
              Games
            </h2>
            <p>Choose which games are tracked and scanned for drops.</p>
          </div>
          <Badge>{statusData?.games_selected.length ?? 0} selected</Badge>
        </div>

        {games.error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{games.error.message}</span>
          </p>
        )}

        <GameSelector games={games.data ?? []} isLoading={games.isLoading} />
      </section>

      <section className="panel settings-section" aria-labelledby="settings-actions">
        <div className="section-head">
          <div>
            <h2 id="settings-actions">
              <Icon name="sparkles" size={18} />
              Actions
            </h2>
            <p>Manual operations run against the backend.</p>
          </div>
        </div>

        <div className="action-grid">
          <article className="action-card">
            <h3>Scan campaigns</h3>
            <p>Fetch campaigns, live streams, and notifications right now.</p>
            <button
              className="btn btn-primary"
              onClick={() => scan.mutate()}
              disabled={scan.isPending}
            >
              <Icon name="scan" size={16} />
              {scan.isPending ? 'Scanning…' : 'Scan now'}
            </button>
            {scan.error && (
              <p className="alert alert-danger" role="alert">
                <Icon name="alert" size={15} />
                <span>{scan.error.message}</span>
              </p>
            )}
            {scan.data && (
              <p className="alert alert-success" role="status">
                <Icon name="check" size={15} />
                <span>
                  Found {scan.data.campaign_count} campaigns, {scan.data.stream_count}{' '}
                  streams, {scan.data.notified_count} notifications.
                </span>
              </p>
            )}
          </article>

          <article className="action-card">
            <h3>Refresh progress</h3>
            <p>Sync drop progress, ETAs, and claim status from Twitch.</p>
            <button
              className="btn btn-secondary"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending || !connected}
              title={connected ? undefined : 'Connect Twitch to refresh progress'}
            >
              <Icon name="refresh" size={16} />
              {refresh.isPending ? 'Refreshing…' : 'Refresh progress'}
            </button>
            {!connected && (
              <p className="muted small">Connect Twitch to enable this action.</p>
            )}
            {refresh.error && (
              <p className="alert alert-danger" role="alert">
                <Icon name="alert" size={15} />
                <span>{refresh.error.message}</span>
              </p>
            )}
            {refresh.data && (
              <p className="alert alert-success" role="status">
                <Icon name="check" size={15} />
                <span>
                  Synced {refresh.data.drop_count} drops from{' '}
                  {refresh.data.campaign_count} campaign(s).
                </span>
              </p>
            )}
          </article>

          <article className="action-card">
            <h3>Test Telegram</h3>
            <p>Send a test notification to verify your Telegram configuration.</p>
            <button
              className="btn btn-secondary"
              onClick={() => testTelegram.mutate()}
              disabled={testTelegram.isPending || !statusData?.telegram_configured}
              title={
                statusData?.telegram_configured
                  ? undefined
                  : 'Telegram is not configured'
              }
            >
              <Icon name="link" size={16} />
              {testTelegram.isPending ? 'Sending…' : 'Test Telegram'}
            </button>
            {!statusData?.telegram_configured && !status.isLoading && (
              <p className="muted small">Telegram is not configured in .env.</p>
            )}
            {testTelegram.error && (
              <p className="alert alert-danger" role="alert">
                <Icon name="alert" size={15} />
                <span>{testTelegram.error.message}</span>
              </p>
            )}
            {testTelegram.data && (
              <p className="alert alert-success" role="status">
                <Icon name="check" size={15} />
                <span>Telegram test sent.</span>
              </p>
            )}
          </article>
        </div>
      </section>

      <section className="panel settings-section" aria-labelledby="settings-twitch">
        <div className="section-head">
          <div>
            <h2 id="settings-twitch">
              <Icon name="twitch" size={18} />
              Twitch connection
            </h2>
            <p>Authorize read-only access to drop progress on your account.</p>
          </div>
          {twitch.isLoading ? (
            <Badge tone="muted">Checking…</Badge>
          ) : (
            <Badge tone={connected ? 'success' : 'warning'} dot>
              {connected ? 'Connected' : 'Not connected'}
            </Badge>
          )}
        </div>

        {twitch.error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{twitch.error.message}</span>
          </p>
        )}

        <div className="settings-status-row">
          {connected ? (
            <>
              <Avatar
                name={twitch.data?.display_name || twitch.data?.login}
                src={twitch.data?.profile_image_url}
                size="md"
              />
              <div className="settings-status-copy">
                <strong>
                  {twitch.data?.display_name || twitch.data?.login || 'Twitch user'}
                </strong>
                <span className="muted small">
                  @{twitch.data?.login || 'unknown'} · Token expires{' '}
                  {formatDateTime(twitch.data?.expires_at)}
                </span>
              </div>
            </>
          ) : (
            <>
              <span className="connect-hero-icon connect-hero-icon-sm" aria-hidden="true">
                <Icon name="twitch" size={20} />
              </span>
              <div className="settings-status-copy">
                <strong>No Twitch account connected</strong>
                <span className="muted small">
                  Connect to enable progress tracking and ready-to-claim status.
                </span>
              </div>
            </>
          )}

          <div className="inline-actions">
            <button
              className="btn btn-secondary"
              onClick={connect.start}
              disabled={connect.starting}
            >
              <Icon name="twitch" size={16} />
              {connect.starting
                ? 'Starting…'
                : connected
                  ? 'Reconnect'
                  : 'Connect Twitch'}
            </button>
            {connected && (
              <button
                className="btn btn-danger"
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
              >
                <Icon name="logout" size={16} />
                {logout.isPending ? 'Disconnecting…' : 'Disconnect'}
              </button>
            )}
          </div>
        </div>

        {logout.error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{logout.error.message}</span>
          </p>
        )}

        <TwitchConnect connect={connect} />
      </section>

      <section className="panel settings-section" aria-labelledby="settings-system">
        <div className="section-head">
          <div>
            <h2 id="settings-system">
              <Icon name="settings" size={18} />
              System
            </h2>
            <p>Read-only values reported by the backend.</p>
          </div>
          <Badge tone="accent">Managed by .env</Badge>
        </div>

        <p className="notice">
          <Icon name="alert" size={15} />
          <span>
            Scan and progress intervals, credentials, and notification settings are
            configured in the backend <code>.env</code> file. They are read-only here.
          </span>
        </p>

        {status.isLoading && <LoadingState label="Loading system status…" />}

        {status.error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{status.error.message}</span>
          </p>
        )}

        {statusData && (
          <dl className="kv-grid">
            <div className="kv">
              <dt>Scan interval</dt>
              <dd>{formatSeconds(statusData.poll_seconds)}</dd>
            </div>
            <div className="kv">
              <dt>Minimum scan interval</dt>
              <dd>{formatSeconds(statusData.min_poll_seconds)}</dd>
            </div>
            <div className="kv">
              <dt>Progress interval</dt>
              <dd>{formatSeconds(statusData.progress_poll_seconds)}</dd>
            </div>
            <div className="kv">
              <dt>Minimum progress interval</dt>
              <dd>{formatSeconds(statusData.min_progress_poll_seconds)}</dd>
            </div>
            <div className="kv">
              <dt>Twitch API</dt>
              <dd>{configuredBadge(statusData.twitch_configured)}</dd>
            </div>
            <div className="kv">
              <dt>Telegram</dt>
              <dd>{configuredBadge(statusData.telegram_configured)}</dd>
            </div>
            <div className="kv">
              <dt>Drops API key</dt>
              <dd>{configuredBadge(statusData.drops_api_keyed)}</dd>
            </div>
            <div className="kv">
              <dt>Last scan</dt>
              <dd>{formatDateTime(statusData.last_scan?.started_at)}</dd>
            </div>
            <div className="kv">
              <dt>Last scan result</dt>
              <dd>
                {statusData.last_scan ? (
                  statusData.last_scan.ok ? (
                    <Badge tone="success" dot>
                      OK
                    </Badge>
                  ) : (
                    <Badge tone="danger" dot>
                      Failed
                    </Badge>
                  )
                ) : (
                  'Never'
                )}
              </dd>
            </div>
            <div className="kv">
              <dt>Selected games</dt>
              <dd>{statusData.games_selected.length}</dd>
            </div>
          </dl>
        )}

        {statusData?.last_error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>Last error: {statusData.last_error}</span>
          </p>
        )}
      </section>
    </div>
  )
}
