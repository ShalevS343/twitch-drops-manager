import type { WatchSession } from '../hooks/useWatchSession'
import { formatClock, formatDuration, formatRemaining } from '../lib/format'
import type { WatchSuggestion } from '../lib/watchQueue'
import { Badge } from './ui/Badge'
import { Icon } from './ui/Icon'

interface WatchSessionPanelProps {
  session: WatchSession
  elapsedMs: number
  isRunning: boolean
  suggestions: WatchSuggestion[]
  onPause: () => void
  onResume: () => void
  onStop: () => void
  onSwitch: (suggestion: WatchSuggestion) => void
}

export function WatchSessionPanel({
  session,
  elapsedMs,
  isRunning,
  suggestions,
  onPause,
  onResume,
  onStop,
  onSwitch,
}: WatchSessionPanelProps) {
  const targetMs = Math.max(0, session.targetMinutes) * 60_000
  const complete = targetMs === 0 || elapsedMs >= targetMs
  const percent =
    targetMs === 0 ? 100 : Math.min(100, (elapsedMs / targetMs) * 100)
  const remainingMs = Math.max(0, targetMs - elapsedMs)
  const startedAt = new Date(session.startedAt).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })

  return (
    <section className="panel watch-session" aria-label="Current watch session">
      <div className="watch-session-head">
        <div className="watch-session-copy">
          <div className="badge-row">
            <Badge tone="accent" dot>
              Manual session
            </Badge>
            {isRunning ? (
              <Badge tone="live" dot>
                Timer running
              </Badge>
            ) : (
              <Badge tone="warning">Paused</Badge>
            )}
            {complete && <Badge tone="success">Target reached</Badge>}
          </div>
          <h2>{session.campaignName}</h2>
          <p className="card-meta">
            {session.gameName || 'Unknown game'}
            <span className="meta-sep">·</span>
            {session.userName || session.userLogin}
            <span className="meta-sep">·</span>
            {session.streamTitle || 'Untitled stream'}
          </p>
        </div>

        <a
          className="btn btn-secondary btn-sm"
          href={session.streamUrl}
          target="_blank"
          rel="noreferrer"
        >
          <Icon name="play" size={14} />
          Open stream on Twitch
        </a>
      </div>

      <div className="watch-session-timer">
        <span className="watch-session-clock">{formatClock(elapsedMs)}</span>
        <span className="watch-session-target">
          of {formatDuration(session.targetMinutes)} estimated campaign time
        </span>
      </div>

      <div
        className="progress-track watch-session-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
        aria-label="Watch session progress"
      >
        <span
          className={`progress-fill${complete ? ' ready' : ''}`}
          style={{ width: `${percent}%` }}
        />
      </div>

      <div className="watch-session-meta">
        <span>
          {complete
            ? 'Estimated target reached — check Twitch before moving on.'
            : `${formatDuration(remainingMs / 60_000)} left on the timer.`}
        </span>
        <span>Started at {startedAt}</span>
      </div>

      <div className="card-footer watch-session-actions">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={isRunning ? onPause : onResume}
        >
          <Icon name={isRunning ? 'clock' : 'play'} size={15} />
          {isRunning ? 'Pause watch timer' : 'Resume watch timer'}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onStop}>
          <Icon name="x" size={15} />
          Stop watch timer
        </button>
        {complete && suggestions.length > 0 && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onSwitch(suggestions[0])}
          >
            <Icon name="arrow-right" size={15} />
            Stop timer &amp; start next
          </button>
        )}
      </div>

      {suggestions.length > 0 && (
        <div className="watch-session-next">
          <div className="section-label">
            <span>Next up</span>
            <small>Manual handoff</small>
          </div>
          <ul className="next-list">
            {suggestions.map((suggestion) => (
              <li key={suggestion.campaign.campaign_id}>
                <div>
                  <strong>{suggestion.campaign.campaign_name}</strong>
                  <span>
                    {suggestion.stream.user_name || suggestion.stream.user_login}
                    <span className="meta-sep">·</span>
                    {formatRemaining(suggestion.campaign.remaining_minutes)} left
                    <span className="meta-sep">·</span>
                    {suggestion.stream.game_name || 'Unknown game'}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => onSwitch(suggestion)}
                >
                  Switch campaign
                  <Icon name="arrow-right" size={13} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
