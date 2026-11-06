import type { WatchQueueCampaign, WatchQueueItem } from '../api/types'
import { endsSoon, formatRemaining, formatTimeUntil } from '../lib/format'
import { Badge } from './ui/Badge'
import { Icon } from './ui/Icon'

interface WatchQueueCardProps {
  item: WatchQueueItem
  onWatch: (stream: WatchQueueItem, campaign: WatchQueueCampaign) => void
  activeCampaignId: string | null
  activeStreamId: number | null
  sessionActive: boolean
}

export function WatchQueueCard({
  item,
  onWatch,
  activeCampaignId,
  activeStreamId,
  sessionActive,
}: WatchQueueCardProps) {
  const hasEndingSoon = item.campaigns.some((campaign) => endsSoon(campaign.ends_at))
  const isActiveStream =
    item.stream_id === activeStreamId &&
    item.campaigns.some((campaign) => campaign.campaign_id === activeCampaignId)

  return (
    <article className={`card queue-card${isActiveStream ? ' active' : ''}`}>
      <header className="card-head">
        <div className="badge-row">
          <Badge>{item.game_name || 'Unknown game'}</Badge>
          <Badge tone="live" dot>
            Live
          </Badge>
          {isActiveStream && (
            <Badge tone="accent" dot>
              Current session
            </Badge>
          )}
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
          const isActive =
            isActiveStream && campaign.campaign_id === activeCampaignId
          const canWatch = remainingMinutes > 0

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
                {formatRemaining(remainingMinutes)} left
              </span>
              <div className="queue-campaign-actions">
                {isActive ? (
                  <Badge tone="accent" dot>
                    Watching now
                  </Badge>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => onWatch(item, campaign)}
                    disabled={sessionActive || !canWatch}
                    title={
                      sessionActive
                        ? 'Stop the current watch timer first'
                        : canWatch
                          ? 'Start a local manual watch timer for this campaign'
                          : 'No watch time left in this campaign'
                    }
                  >
                    <Icon name="play" size={13} />
                    {sessionActive
                      ? 'Timer already running'
                      : canWatch
                        ? 'Start watch timer'
                        : 'Complete'}
                  </button>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      <div className="card-footer">
        <a
          className="btn btn-ghost btn-sm"
          href={item.url}
          target="_blank"
          rel="noreferrer"
        >
          <Icon name="external" size={14} />
          Open stream on Twitch
        </a>
      </div>
    </article>
  )
}
