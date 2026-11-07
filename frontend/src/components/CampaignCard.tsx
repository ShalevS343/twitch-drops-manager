import type { Campaign } from '../api/types'
import { campaignPhase } from '../lib/campaigns'
import {
  endsSoon,
  formatDateTime,
  formatTimeUntil,
  titleCase,
} from '../lib/format'
import { Badge, type BadgeTone } from './ui/Badge'
import { Icon } from './ui/Icon'

function statusTone(campaign: Campaign): BadgeTone {
  const phase = campaignPhase(campaign)
  if (phase === 'active') return 'success'
  if (phase === 'upcoming') return 'accent'
  if (phase === 'ended') return 'muted'
  return 'neutral'
}

export function CampaignCard({ campaign }: { campaign: Campaign }) {
  const phase = campaignPhase(campaign)
  const completed = campaign.completed === true
  const isEndingSoon =
    !completed && phase === 'active' && endsSoon(campaign.ends_at)

  return (
    <article className={`card campaign-card${completed ? ' completed' : ''}`}>
      <header className="card-head">
        <div className="badge-row">
          <Badge>{campaign.game.name}</Badge>
          {completed ? (
            <Badge tone="success" dot>
              Completed
            </Badge>
          ) : (
            <Badge tone={statusTone(campaign)} dot={phase === 'active'}>
              {titleCase(campaign.status)}
            </Badge>
          )}
          {isEndingSoon && (
            <Badge tone="warning" dot>
              Ending soon
            </Badge>
          )}
        </div>
      </header>

      <div>
        <h3>{campaign.name}</h3>
        <p className="card-meta">
          <Icon name="user" size={14} />
          {campaign.owner_name || 'Unknown publisher'}
        </p>
        <p className="card-meta">
          <Icon name="clock" size={14} />
          {campaign.ends_at
            ? `Ends ${formatDateTime(campaign.ends_at)} (${formatTimeUntil(campaign.ends_at)})`
            : 'No end date listed'}
        </p>
      </div>

      {campaign.rewards.length > 0 && (
        <ul className="rewards">
          {campaign.rewards.map((reward) => (
            <li key={reward.id} className="reward">
              <div className="reward-main">
                <strong>{reward.name}</strong>
                {reward.benefit_name && <small>{reward.benefit_name}</small>}
              </div>
              <span className="reward-minutes">{reward.required_minutes} min</span>
            </li>
          ))}
        </ul>
      )}

      {campaign.details_url && (
        <div className="card-footer">
          <a
            className="btn btn-secondary btn-sm"
            href={campaign.details_url}
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="external" size={14} />
            View campaign on Twitch
          </a>
        </div>
      )}
    </article>
  )
}
