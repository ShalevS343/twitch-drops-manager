import type { Stream } from '../api/types'
import { safeExternalUrl } from '../lib/url'
import { Badge } from './ui/Badge'
import { Icon } from './ui/Icon'

export function StreamCard({ stream }: { stream: Stream }) {
  const streamUrl = safeExternalUrl(stream.url)

  return (
    <article className="card stream-card">
      <header className="card-head">
        <div className="badge-row">
          <Badge>{stream.game.name}</Badge>
          <Badge tone="live" dot>
            Live
          </Badge>
        </div>
      </header>

      <div>
        <h3>{stream.user_name || stream.user_login}</h3>
        <p className="stream-title">{stream.title || 'Untitled stream'}</p>
        <p className="card-meta">
          <Icon name="radio" size={14} />
          {stream.viewers.toLocaleString()} viewers
          <span className="meta-sep">·</span>
          {stream.language || 'unknown language'}
        </p>
      </div>

      <div className="stream-campaigns">
        <span className="section-label">Matching campaigns</span>
        {stream.matching_campaigns.length > 0 ? (
          <div className="chip-list">
            {stream.matching_campaigns.map((campaign) => (
              <span className="chip chip-static" key={campaign}>
                {campaign}
              </span>
            ))}
          </div>
        ) : (
          <p className="muted small">No matching campaigns.</p>
        )}
      </div>

      <div className="card-footer">
        {streamUrl && (
          <a
            className="btn btn-primary btn-sm"
            href={streamUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Icon name="play" size={14} />
            Open stream on Twitch
          </a>
        )}
      </div>
    </article>
  )
}
