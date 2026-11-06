import type { Status } from '../api/types'
import { useScan, useTestTelegram } from '../hooks/useApi'

interface Props {
  status?: Status
  isLoading: boolean
  error: Error | null
}

export function StatusPanel({ status, isLoading, error }: Props) {
  const scan = useScan()
  const test = useTestTelegram()

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Status</h2>
          {isLoading && <p className="muted">Loading…</p>}
          {error && <p className="error">{error.message}</p>}
          {status && (
            <ul className="facts">
              <li>
                <span>Selected games</span>
                <strong>{status.games_selected.join(', ') || 'None'}</strong>
              </li>
              <li>
                <span>Campaigns</span>
                <strong>{status.campaign_count}</strong>
              </li>
              <li>
                <span>Live streams</span>
                <strong>{status.stream_count}</strong>
              </li>
              <li>
                <span>Last scan</span>
                <strong>
                  {status.last_scan ? new Date(status.last_scan.started_at).toLocaleString() : 'Never'}
                </strong>
              </li>
              <li>
                <span>Twitch API</span>
                <strong>{status.twitch_configured ? 'Configured' : 'Missing'}</strong>
              </li>
              <li>
                <span>Telegram</span>
                <strong>{status.telegram_configured ? 'Configured' : 'Missing'}</strong>
              </li>
            </ul>
          )}
          {status?.last_error && <p className="error">Last error: {status.last_error}</p>}
        </div>

        <div className="actions">
          <button onClick={() => scan.mutate()} disabled={scan.isPending}>
            {scan.isPending ? 'Scanning…' : 'Scan now'}
          </button>
          <button
            className="secondary"
            onClick={() => test.mutate()}
            disabled={test.isPending || !status?.telegram_configured}
          >
            Test Telegram
          </button>
        </div>
      </div>

      {scan.error && <p className="error">{scan.error.message}</p>}
      {scan.data && (
        <p className="success">
          Found {scan.data.campaign_count} campaigns, {scan.data.stream_count} streams,{' '}
          {scan.data.notified_count} notifications.
        </p>
      )}
      {test.error && <p className="error">{test.error.message}</p>}
      {test.data && <p className="success">Telegram test sent.</p>}
    </section>
  )
}
