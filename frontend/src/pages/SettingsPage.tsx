import { useEffect, useState } from 'react'

import { DeviceConnect, useDeviceConnect } from '../components/DeviceConnect'
import { GameSelector } from '../components/GameSelector'
import {
  TwitchConnectAdvanced,
  useTwitchConnect,
} from '../components/TwitchConnect'
import { Avatar } from '../components/ui/Avatar'
import { Badge } from '../components/ui/Badge'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { useAuth } from '../auth/AuthContext'
import {
  useAdminUsers,
  useCreateTelegramLink,
  useGames,
  useRefreshProgress,
  useScan,
  useTestTelegram,
  useTwitchDisconnect,
  useUnlinkTelegram,
  useUpdateAdminUser,
  useUpdateMe,
  type StatusQuery,
  type TwitchStatusQuery,
} from '../hooks/useApi'
import { formatDateTime, formatSeconds } from '../lib/format'
import { safeExternalUrl } from '../lib/url'

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
  const { user, isAdmin, telegramBotConfigured, refresh } = useAuth()
  const games = useGames()
  const scan = useScan()
  const refreshProgress = useRefreshProgress()
  const testTelegram = useTestTelegram()
  const createLink = useCreateTelegramLink()
  const unlink = useUnlinkTelegram()
  const disconnect = useTwitchDisconnect()
  const connect = useTwitchConnect({ onConnected: refresh })
  const device = useDeviceConnect({ mode: 'reconnect' })
  const updateMe = useUpdateMe()
  const adminUsers = useAdminUsers()
  const updateUser = useUpdateAdminUser()

  const [telegramEnabled, setTelegramEnabled] = useState(user?.telegram_enabled ?? false)
  const [waitingForTelegram, setWaitingForTelegram] = useState(false)
  const [linkTimedOut, setLinkTimedOut] = useState(false)
  const [blockedLink, setBlockedLink] = useState<string | null>(null)
  const botUsername = createLink.data?.bot_username

  useEffect(() => {
    setTelegramEnabled(user?.telegram_enabled ?? false)
  }, [user?.telegram_chat_id, user?.telegram_enabled])

  // While waiting for the bot's /start reply, re-check the session until the
  // chat id appears. Give up after two minutes so a forgotten tab stops polling.
  useEffect(() => {
    if (!waitingForTelegram) return

    const interval = window.setInterval(() => {
      void refresh()
    }, 3000)
    const timeout = window.setTimeout(() => {
      setWaitingForTelegram(false)
      setLinkTimedOut(true)
    }, 120_000)

    return () => {
      window.clearInterval(interval)
      window.clearTimeout(timeout)
    }
  }, [waitingForTelegram, refresh])

  useEffect(() => {
    if (waitingForTelegram && user?.telegram_chat_id?.trim()) {
      setWaitingForTelegram(false)
      setLinkTimedOut(false)
    }
  }, [waitingForTelegram, user?.telegram_chat_id])

  const connected = twitch.data?.connected === true
  const statusData = status.data

  const savedChatId = user?.telegram_chat_id?.trim() ?? ''
  const blockedUrl = safeExternalUrl(blockedLink)
  const telegramDirty = telegramEnabled !== (user?.telegram_enabled ?? false)
  const canSaveTelegram =
    !updateMe.isPending && Boolean(savedChatId) && telegramDirty
  const canTestTelegram =
    telegramBotConfigured &&
    Boolean(savedChatId) &&
    user?.telegram_enabled === true &&
    !testTelegram.isPending

  function saveTelegram() {
    updateMe.mutate({ telegram_enabled: telegramEnabled })
  }

  async function connectTelegram() {
    if (!telegramBotConfigured || createLink.isPending) return

    setLinkTimedOut(false)
    setBlockedLink(null)
    // Open the tab before awaiting so popup blockers still allow the redirect.
    const tab = window.open('about:blank', '_blank')
    if (tab) tab.opener = null
    try {
      const link = await createLink.mutateAsync()
      const deepLink = safeExternalUrl(link.deep_link)
      if (!deepLink) {
        tab?.close()
        return
      }
      if (tab) {
        tab.location.href = deepLink
        setWaitingForTelegram(true)
      } else {
        setWaitingForTelegram(false)
        setBlockedLink(deepLink)
      }
    } catch {
      tab?.close()
    }
  }

  function unlinkTelegram() {
    if (unlink.isPending) return
    setWaitingForTelegram(false)
    setLinkTimedOut(false)
    setBlockedLink(null)
    unlink.mutate()
  }

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

      <section className="panel settings-section" aria-labelledby="settings-telegram">
        <div className="section-head">
          <div>
            <h2 id="settings-telegram">
              <Icon name="link" size={18} />
              Telegram alerts
            </h2>
            <p>Send ready-to-claim alerts to your own Telegram chat.</p>
          </div>
          {!telegramBotConfigured ? (
            <Badge tone="warning" dot>
              Bot not configured
            </Badge>
          ) : user?.telegram_enabled && savedChatId ? (
            <Badge tone="success" dot>
              On
            </Badge>
          ) : (
            <Badge tone="muted" dot>
              Off
            </Badge>
          )}
        </div>

        <div className="telegram-form">
          {savedChatId ? (
            <div className="inline-actions">
              <p className="muted small">
                Linked to Telegram chat <code>{savedChatId}</code>.
              </p>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={unlinkTelegram}
                disabled={unlink.isPending}
              >
                <Icon name="logout" size={14} />
                {unlink.isPending ? 'Unlinking…' : 'Unlink Telegram'}
              </button>
            </div>
          ) : !telegramBotConfigured ? (
            <p className="muted small">
              This server has no Telegram bot token yet, so alerts and tests cannot
              be sent. Ask the admin to configure it.
            </p>
          ) : waitingForTelegram ? (
            <>
              <p className="alert alert-warning" role="status">
                <Icon name="clock" size={15} />
                <span>Waiting for Telegram… Press Start in Telegram.</span>
              </p>
              <div className="inline-actions">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setWaitingForTelegram(false)}
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <>
              <button
                type="button"
                className="btn btn-primary"
                onClick={connectTelegram}
                disabled={createLink.isPending}
              >
                <Icon name="link" size={16} />
                {createLink.isPending ? 'Opening Telegram…' : 'Connect Telegram'}
              </button>
              <p className="muted small">
                {botUsername ? (
                  <>
                    Opens <code>@{botUsername}</code> in a new tab. Press Start
                    there to finish.
                  </>
                ) : (
                  <>
                    Opens the Telegram bot in a new tab. Press Start there to
                    finish.
                  </>
                )}
              </p>
            </>
          )}

          {blockedUrl && (
            <p className="alert alert-warning" role="status">
              <Icon name="alert" size={15} />
              <span>
                Your browser blocked the Telegram tab.{' '}
                <a
                  href={blockedUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => {
                    setBlockedLink(null)
                    setWaitingForTelegram(true)
                  }}
                >
                  Open Telegram
                </a>{' '}
                to finish linking, then come back here.
              </span>
            </p>
          )}

          {linkTimedOut && !savedChatId && !waitingForTelegram && (
            <p className="alert alert-warning" role="status">
              <Icon name="alert" size={15} />
              <span>
                Still not connected. Press Start in Telegram, then try Connect
                Telegram again.
              </span>
            </p>
          )}

          {createLink.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={15} />
              <span>{createLink.error.message}</span>
            </p>
          )}
          {unlink.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={15} />
              <span>{unlink.error.message}</span>
            </p>
          )}

          {savedChatId && (
            <>
              <label className="toggle-row" htmlFor="telegram-enabled">
                <input
                  id="telegram-enabled"
                  type="checkbox"
                  checked={telegramEnabled}
                  onChange={(event) => setTelegramEnabled(event.target.checked)}
                />
                <span>
                  <strong>Send Telegram alerts for this account</strong>
                  <span className="muted small">
                    Turning this off clears queued campaign alerts.
                  </span>
                </span>
              </label>

              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={saveTelegram}
                  disabled={!canSaveTelegram}
                >
                  <Icon name="check" size={16} />
                  {updateMe.isPending ? 'Saving…' : 'Save Telegram settings'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => testTelegram.mutate()}
                  disabled={!canTestTelegram}
                  title={
                    !telegramBotConfigured
                      ? 'Telegram is not configured on this server'
                      : user?.telegram_enabled !== true
                        ? 'Enable Telegram alerts for this account first'
                        : 'Send a test message to your chat'
                  }
                >
                  <Icon name="link" size={16} />
                  {testTelegram.isPending ? 'Sending…' : 'Send test message'}
                </button>
              </div>
            </>
          )}

          {updateMe.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={15} />
              <span>{updateMe.error.message}</span>
            </p>
          )}
          {updateMe.isSuccess && !telegramDirty && (
            <p className="alert alert-success" role="status">
              <Icon name="check" size={15} />
              <span>Telegram settings saved.</span>
            </p>
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
              <span>Test message sent to your Telegram chat.</span>
            </p>
          )}
        </div>
      </section>

      <section className="panel settings-section" aria-labelledby="settings-actions">
        <div className="section-head">
          <div>
            <h2 id="settings-actions">
              <Icon name="sparkles" size={18} />
              Actions
            </h2>
            <p>Manual operations available for your account.</p>
          </div>
        </div>

        <div className="action-grid">
          {isAdmin && (
            <article className="action-card">
              <h3>Scan for new drops</h3>
              <p>Fetch campaigns, live streams, and notifications for everyone.</p>
              <button
                className="btn btn-primary"
                onClick={() => scan.mutate()}
                disabled={scan.isPending}
              >
                <Icon name="scan" size={16} />
                {scan.isPending ? 'Scanning…' : 'Scan for new drops'}
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
          )}

          <article className="action-card">
            <h3>Sync drop progress</h3>
            <p>Sync drop progress and claim status from Twitch.</p>
            <button
              className="btn btn-secondary"
              onClick={() => refreshProgress.mutate()}
              disabled={refreshProgress.isPending || !connected}
              title={
                connected
                  ? 'Sync your Twitch drop progress'
                  : 'Connect Twitch to sync drop progress'
              }
            >
              <Icon name="refresh" size={16} />
              {refreshProgress.isPending ? 'Syncing…' : 'Sync drop progress'}
            </button>
            {!connected && (
              <p className="muted small">Connect Twitch to enable this action.</p>
            )}
            {refreshProgress.error && (
              <p className="alert alert-danger" role="alert">
                <Icon name="alert" size={15} />
                <span>{refreshProgress.error.message}</span>
              </p>
            )}
            {refreshProgress.data && !refreshProgress.data.connected && (
              <p className="alert alert-warning" role="alert">
                <Icon name="alert" size={15} />
                <span>
                  Twitch reconnect required before drop progress can sync.
                </span>
              </p>
            )}
            {refreshProgress.data?.connected && (
              <p className="alert alert-success" role="status">
                <Icon name="check" size={15} />
                <span>
                  Synced {refreshProgress.data.drop_count} drops from{' '}
                  {refreshProgress.data.campaign_count} campaign(s).
                </span>
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
            <p>Authorize access to drop progress on your account.</p>
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
              onClick={device.start}
              disabled={device.starting}
            >
              <Icon name="twitch" size={16} />
              {device.starting
                ? 'Starting…'
                : connected
                  ? 'Reconnect with code'
                  : 'Connect with code'}
            </button>
            {connected && (
              <button
                className="btn btn-danger"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
              >
                <Icon name="logout" size={16} />
                {disconnect.isPending ? 'Disconnecting…' : 'Disconnect Twitch'}
              </button>
            )}
          </div>
        </div>

        {disconnect.error && (
          <p className="alert alert-danger" role="alert">
            <Icon name="alert" size={16} />
            <span>{disconnect.error.message}</span>
          </p>
        )}

        <DeviceConnect connect={device} showStart={false} />
        <TwitchConnectAdvanced connect={connect} />
      </section>

      {isAdmin && (
        <section className="panel settings-section" aria-labelledby="settings-users">
          <div className="section-head">
            <div>
              <h2 id="settings-users">
                <Icon name="user" size={18} />
                Users
              </h2>
              <p>Enable or disable access for accounts on this server.</p>
            </div>
            <Badge tone="accent">{adminUsers.data?.length ?? 0} accounts</Badge>
          </div>

          {adminUsers.isLoading && <LoadingState label="Loading users…" />}

          {adminUsers.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{adminUsers.error.message}</span>
            </p>
          )}

          {updateUser.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{updateUser.error.message}</span>
            </p>
          )}

          {adminUsers.data && adminUsers.data.length > 0 && (
            <ul className="list">
              {adminUsers.data.map((account) => {
                const isSelf = account.id === user?.id
                const active = account.is_active ?? account.active ?? true
                const pending =
                  updateUser.isPending && updateUser.variables?.id === account.id

                return (
                  <li className="list-item" key={account.id}>
                    <Avatar
                      name={account.display_name || account.login}
                      src={account.profile_image_url}
                      size="sm"
                    />
                    <div className="list-item-main">
                      <span className="list-item-title">
                        {account.display_name || account.login}
                        {isSelf ? ' (you)' : ''}
                      </span>
                      <span className="list-item-meta">
                        @{account.login} · {account.role === 'admin' ? 'Admin' : 'User'} ·
                        Last sign-in {formatDateTime(account.last_login_at)}
                      </span>
                    </div>
                    <div className="list-item-actions">
                      {account.telegram_enabled === true && (
                        <Badge tone="accent" title="Telegram alerts enabled">
                          Telegram
                        </Badge>
                      )}
                      <Badge tone={active ? 'success' : 'muted'} dot>
                        {active ? 'Active' : 'Disabled'}
                      </Badge>
                      <button
                        type="button"
                        className={`btn btn-sm ${
                          active ? 'btn-secondary' : 'btn-primary'
                        }`}
                        onClick={() =>
                          updateUser.mutate({
                            id: account.id,
                            isActive: !active,
                          })
                        }
                        disabled={isSelf || pending}
                        title={
                          isSelf
                            ? 'You cannot disable your own account'
                            : active
                              ? 'Disable this account'
                              : 'Enable this account'
                        }
                      >
                        {pending ? 'Saving…' : active ? 'Disable' : 'Enable'}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}

          {adminUsers.data && adminUsers.data.length === 0 && (
            <p className="muted small">No accounts yet.</p>
          )}
        </section>
      )}

      <section className="panel settings-section" aria-labelledby="settings-system">
        <div className="section-head">
          <div>
            <h2 id="settings-system">
              <Icon name="settings" size={18} />
              System
            </h2>
            <p>Values reported by the backend.</p>
          </div>
          <Badge tone="accent">Managed by .env</Badge>
        </div>

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
