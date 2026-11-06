import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'

import { api } from '../api/client'
import type { ProgressCampaign, TwitchConnect } from '../api/types'
import {
  useProgress,
  useRefreshProgress,
  useTwitchLogout,
  useTwitchStatus,
} from '../hooks/useApi'
import { endsSoon, formatEta, formatRemaining } from '../lib/format'

function formatEnd(value: string | null): string {
  if (!value) return 'Unknown'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function ProgressCard({ campaign }: { campaign: ProgressCampaign }) {
  const hasReady = campaign.drops.some((drop) => drop.is_ready)

  return (
    <article className="card progress-card">
      <header>
        <span className="badge">{campaign.game_name || 'Unknown game'}</span>
        <span className="badge">
          {campaign.claimed_count}/{campaign.total_count} claimed
        </span>
        {endsSoon(campaign.campaign_ends_at) && (
          <span className="badge ending-soon">Ends soon</span>
        )}
      </header>

      <h3>{campaign.campaign_name}</h3>
      <p className="muted">
        Ends: {formatEnd(campaign.campaign_ends_at)}
        {campaign.eta_minutes !== null && (
          <> · {formatEta(campaign.eta_minutes)} left</>
        )}
      </p>

      <ul className="progress-drops">
        {campaign.drops.map((drop) => (
          <li key={drop.drop_id}>
            <div className="progress-drop-head">
              <strong>{drop.drop_name}</strong>
              <span className="muted">
                {drop.current_minutes}/{drop.required_minutes} min
              </span>
            </div>

            <div
              className={`progress-bar${drop.is_ready ? ' ready' : ''}${
                drop.is_claimed ? ' claimed' : ''
              }`}
              role="progressbar"
              aria-valuenow={drop.percent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <span style={{ width: `${drop.percent}%` }} />
            </div>

            <p className="progress-drop-eta muted">
              {formatRemaining(drop.remaining_minutes)} left
              {drop.rate_minutes_per_hour !== null && drop.eta_minutes !== null && (
                <> · {formatEta(drop.eta_minutes)} at current pace</>
              )}
            </p>

            <div className="progress-drop-meta">
              {drop.is_claimed && <span className="badge claimed">Claimed</span>}
              {drop.is_ready && <span className="badge ready">Ready to claim</span>}
              {drop.benefits.length > 0 && <small>{drop.benefits.join(', ')}</small>}
            </div>
          </li>
        ))}
      </ul>

      {hasReady && (
        <a href="https://www.twitch.tv/drops/inventory" target="_blank" rel="noreferrer">
          Open Twitch inventory
        </a>
      )}
    </article>
  )
}

export function ProgressPanel() {
  const twitch = useTwitchStatus()
  const progress = useProgress()
  const refresh = useRefreshProgress()
  const logout = useTwitchLogout()
  const queryClient = useQueryClient()

  const [connect, setConnect] = useState<TwitchConnect | null>(null)
  const [redirectUrl, setRedirectUrl] = useState('')
  const [starting, setStarting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const startConnect = async () => {
    setStarting(true)
    setError(null)
    setNotice(null)
    try {
      const info = await api.twitchConnectUrl()
      setConnect(info)
      window.open(info.authorize_url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Twitch login')
    } finally {
      setStarting(false)
    }
  }

  const saveConnect = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const result = await api.twitchConnect(redirectUrl)
      setConnect(null)
      setRedirectUrl('')
      setNotice(
        result.message ??
          `Connected as ${result.login ?? 'Twitch user'}. Your progress is syncing.`,
      )
      await queryClient.invalidateQueries()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the Twitch token')
    } finally {
      setSaving(false)
    }
  }

  const connected = twitch.data?.connected === true

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>My Drop Progress</h2>
          {twitch.isLoading && <p className="muted">Loading Twitch connection…</p>}
          {twitch.error && <p className="error">{twitch.error.message}</p>}

          {connected && (
            <p className="muted">
              Connected as <strong>{twitch.data?.login ?? 'Twitch user'}</strong>. Updated
              automatically every few minutes.
            </p>
          )}

          {!connected && !twitch.isLoading && (
            <p className="muted">
              Connect your Twitch account to see how far along each in-progress drop
              is. Read-only — this app never claims anything for you.
            </p>
          )}

          {notice && <p className="success">{notice}</p>}
          {error && <p className="error">{error}</p>}
        </div>

        <div className="actions">
          {connected ? (
            <>
              <button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
                {refresh.isPending ? 'Refreshing…' : 'Refresh progress'}
              </button>
              <button
                className="secondary"
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
              >
                Disconnect
              </button>
            </>
          ) : (
            <button onClick={startConnect} disabled={starting || !twitch.data}>
              {starting ? 'Starting…' : 'Connect Twitch'}
            </button>
          )}
        </div>
      </div>

      {connect && (
        <div className="device-box">
          <ol className="connect-steps">
            <li>
              <a href={connect.authorize_url} target="_blank" rel="noreferrer">
                Authorize this app on Twitch
              </a>{' '}
              (opens in a new tab), then click <strong>Authorize</strong>.
            </li>
            <li>
              Twitch sends you to <code>twitch.tv/#access_token=…</code>. Copy the{' '}
              <strong>entire URL</strong> from the address bar.
            </li>
            <li>Paste it below and save.</li>
          </ol>

          <form onSubmit={saveConnect}>
            <textarea
              className="redirect-input"
              rows={3}
              value={redirectUrl}
              onChange={(event) => setRedirectUrl(event.target.value)}
              placeholder="https://www.twitch.tv/#access_token=..."
            />
            <div className="actions">
              <button type="submit" disabled={saving || !redirectUrl.trim()}>
                {saving ? 'Saving…' : 'Save connection'}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setConnect(null)
                  setRedirectUrl('')
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {refresh.error && <p className="error">{refresh.error.message}</p>}
      {logout.error && <p className="error">{logout.error.message}</p>}
      {refresh.data && (
        <p className="success">
          Synced {refresh.data.drop_count} drops from {refresh.data.campaign_count}{' '}
          campaign(s).
        </p>
      )}

      {connected && progress.isLoading && <p className="muted">Loading progress…</p>}
      {connected && progress.error && <p className="error">{progress.error.message}</p>}
      {connected && progress.data?.length === 0 && (
        <p className="muted">
          No drops in progress yet. Start watching a Drops-enabled stream on Twitch.
        </p>
      )}

      {connected && (progress.data?.length ?? 0) > 0 && (
        <div className="grid">
          {progress.data?.map((campaign) => (
            <ProgressCard key={campaign.campaign_id} campaign={campaign} />
          ))}
        </div>
      )}
    </section>
  )
}
