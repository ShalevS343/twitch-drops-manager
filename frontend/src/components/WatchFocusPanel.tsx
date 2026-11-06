import type { WatchCandidate, WatchFocus, WatchState } from '../api/types'
import { useFocusWatcher, useSetWatcherEnabled, useStopWatcher, useWatcher } from '../hooks/useApi'
import { formatRemaining, formatTimeUntil } from '../lib/format'
import { Badge } from './ui/Badge'
import { Icon } from './ui/Icon'
import { LoadingState } from './ui/Spinner'

interface WatchFocusPanelProps {
  sessionActive: boolean
  onStartSession: (focus: WatchFocus) => void
}

function reasonCopy(state: WatchState): string | null {
  if (state.status === 'waiting') {
    return 'No eligible live stream is available right now. The watcher will pick one up when the queue refreshes.'
  }

  switch (state.focus?.reason) {
    case 'auto-move':
      return 'The previous focused live left the queue, so the watcher moved to this one automatically.'
    case 'auto':
      return 'Selected the most urgent live campaign in the queue.'
    case 'manual':
      return 'Focus set manually. The watcher will move again if this live leaves the queue.'
    case 'next-unavailable':
      return 'No other live stream is available right now, so the current focus was kept.'
    case 'auto-unavailable':
      return 'No matching live stream is available right now, so the current focus was kept.'
    default:
      return null
  }
}

function candidateLabel(candidate: WatchCandidate): string {
  return `${candidate.user_name || candidate.user_login} · ${
    candidate.game_name || 'Unknown game'
  } · ${formatRemaining(candidate.target_minutes)} left`
}

export function WatchFocusPanel({
  sessionActive,
  onStartSession,
}: WatchFocusPanelProps) {
  const watcher = useWatcher()
  const enable = useSetWatcherEnabled()
  const focus = useFocusWatcher()
  const stop = useStopWatcher()

  const state = watcher.data
  const busy = enable.isPending || focus.isPending || stop.isPending
  const error =
    watcher.error ?? enable.error ?? focus.error ?? stop.error ?? null
  const enabled = state?.enabled ?? false
  const focused = state?.status === 'focused' ? state.focus : null
  const reason = state ? reasonCopy(state) : null

  function dispatch(candidate: WatchCandidate) {
    focus.mutate({
      stream_id: candidate.stream_id,
      campaign_id: candidate.campaign_id,
      strategy: 'manual',
    })
  }

  return (
    <section className="panel watch-focus" aria-label="Focused watcher">
      <div className="section-head">
        <div>
          <h2>
            <Icon name="target" size={18} />
            Focus watcher
          </h2>
          <p>
            Keep one live target selected for the most urgent campaign. One
            watcher at a time; switching focus moves the watcher, not playback.
          </p>
        </div>
        <div className="inline-actions">
          {enabled ? (
            <>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => focus.mutate({ strategy: 'next' })}
                disabled={busy}
              >
                <Icon name="arrow-right" size={13} />
                Next live
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => stop.mutate()}
                disabled={busy}
              >
                <Icon name="x" size={13} />
                Stop watcher
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => enable.mutate(true)}
              disabled={busy}
            >
              <Icon name="target" size={14} />
              Enable focused mode
            </button>
          )}
        </div>
      </div>

      <div className="badge-row watch-focus-badges">
        <Badge tone={enabled ? 'accent' : 'muted'} dot={enabled}>
          {enabled ? 'Focused mode' : 'Off'}
        </Badge>
        <Badge tone="muted">{state?.max_watchers ?? 1} watcher max</Badge>
        {enabled && (
          <Badge tone={state?.status === 'focused' ? 'success' : 'warning'} dot>
            {state?.status === 'focused' ? 'Target locked' : 'Waiting for a live'}
          </Badge>
        )}
        {enabled && state?.auto_move && (
          <Badge tone="neutral">
            <Icon name="refresh" size={11} /> Auto-move on
          </Badge>
        )}
      </div>

      {watcher.isLoading && <LoadingState label="Loading focused watcher…" />}

      {error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{error.message}</span>
        </p>
      )}

      {!watcher.isLoading && !error && !enabled && (
        <div className="watch-focus-empty">
          <p>
            Focused mode lets the watcher follow one live stream at a time. It
            only updates this target and the manual session handoff; it never
            plays, controls, or simulates watching on Twitch.
          </p>
        </div>
      )}

      {enabled && focused && (
        <div className="watch-focus-target">
          <div className="watch-focus-copy">
            <div className="badge-row">
              <Badge tone="live" dot>
                Live
              </Badge>
              <Badge>{focused.game_name || 'Unknown game'}</Badge>
            </div>
            <h3>{focused.user_name || focused.user_login}</h3>
            <p className="stream-title">
              {focused.stream_title || 'Untitled stream'}
            </p>
            <p className="card-meta">
              <Icon name="gift" size={13} />
              {focused.campaign_name}
              <span className="meta-sep">·</span>
              {formatRemaining(focused.target_minutes)} left
              {focused.ends_at && (
                <>
                  <span className="meta-sep">·</span>
                  Campaign ends {formatTimeUntil(focused.ends_at)}
                </>
              )}
            </p>
            {reason && <p className="watch-focus-reason">{reason}</p>}
          </div>
          <div className="watch-focus-actions">
            <a
              className="btn btn-secondary btn-sm"
              href={focused.stream_url}
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="external" size={13} />
              Open stream
            </a>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => onStartSession(focused)}
              disabled={sessionActive}
              title={
                sessionActive
                  ? 'Stop the current manual session first'
                  : 'Start the local manual timer for this target'
              }
            >
              <Icon name="play" size={13} />
              {sessionActive ? 'Session active' : 'Start manual session'}
            </button>
          </div>
        </div>
      )}

      {enabled && state?.status === 'waiting' && reason && (
        <p className="watch-focus-reason watch-focus-waiting">{reason}</p>
      )}

      {enabled && (state?.candidates.length ?? 0) > 0 && (
        <div className="watch-focus-candidates">
          <div className="section-label">
            <span>Change focus</span>
            <small>{state?.candidates.length} other live target(s)</small>
          </div>
          <ul className="next-list">
            {state?.candidates.map((candidate) => (
              <li key={`${candidate.stream_id}-${candidate.campaign_id}`}>
                <div>
                  <strong>{candidate.user_name || candidate.user_login}</strong>
                  <span>{candidateLabel(candidate)}</span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => dispatch(candidate)}
                  disabled={busy}
                >
                  Focus
                  <Icon name="target" size={12} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {enabled && (
        <p className="watch-session-note">
          <Icon name="alert" size={14} />
          The watcher is a queue focus pointer only. It never sends watch
          heartbeats, plays a stream, or simulates viewing.
        </p>
      )}
    </section>
  )
}
