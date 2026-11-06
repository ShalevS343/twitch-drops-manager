import type { WatchQueueItem } from '../api/types'
import { endsSoon, formatEta, formatRemaining, formatTimeUntil } from '../lib/format'
import { Badge } from './ui/Badge'
import { Icon } from './ui/Icon'

export function WatchQueueCard({ item }: { item: WatchQueueItem }) {
  const hasEndingSoon = item.campaigns.some((campaign) => endsSoon(campaign.ends_at))

  return (
    <article className="card queue-card">
      <header className="card-head">
        <div className="badge-row">
          <Badge>{item.game_name || 'Unknown game'}</Badge>
          <Badge tone="live" dot>
            Live
          </Badge>
          {hasEndingSoon && (
            <Badge tone="warning" dot>
              Ending soon
            </Badge>
          )}
        </div>
      </header>

      <div>
        <h3>{item.user_name || item.user_login}</h3>
        <p className="stream-title">{item.title || 'Untitled stream'}</p>
        <p className="card-meta">
          <Icon name="radio" size={14} />
          {item.viewers.toLocaleString()} viewers
          <span className="meta-sep">·</span>
          {item.language || 'unknown language'}
        </p>
      </div>

      <ul className="queue-campaigns">
        {item.campaigns.map((campaign) => {
          const remainingMinutes =
            campaign.next_drop_remaining_minutes ?? campaign.remaining_minutes

          return (
            <li className="queue-campaign" key={campaign.campaign_id}>
              <div className="queue-campaign-head">
                <strong>{campaign.campaign_name}</strong>
                {endsSoon(campaign.ends_at) && (
                  <Badge tone="warning">Ends {formatTimeUntil(campaign.ends_at)}</Badge>
                )}
              </div>
              <span className="queue-campaign-next">
                {campaign.next_drop_name
                  ? `Next drop: ${campaign.next_drop_name}`
                  : 'No upcoming drop'}
              </span>
              <span className="queue-campaign-meta">
                {formatRemaining(remainingMinutes)} left · ETA{' '}
                {formatEta(campaign.eta_minutes)}
              </span>
            </li>
          )
        })}
      </ul>

      <div className="card-footer">
        <a
          className="btn btn-primary btn-sm"
          href={item.url}
          target="_blank"
          rel="noreferrer"
        >
          <Icon name="play" size={14} />
          Watch
        </a>
      </div>
    </article>
  )
}
