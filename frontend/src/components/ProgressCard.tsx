import type { ProgressCampaign } from '../api/types'
import { endsSoon, formatDateTime, formatEta, formatRemaining } from '../lib/format'
import { Badge } from './ui/Badge'
import { Icon } from './ui/Icon'

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)))
}

export function ProgressCard({ campaign }: { campaign: ProgressCampaign }) {
  const hasReady = campaign.drops.some((drop) => drop.is_ready && !drop.is_claimed)
  const unclaimed = campaign.drops.filter((drop) => !drop.is_claimed)

  return (
    <article className="card progress-card">
      <header className="card-head">
        <div className="badge-row">
          <Badge>{campaign.game_name || 'Unknown game'}</Badge>
          <Badge tone="neutral">
            {campaign.claimed_count}/{campaign.total_count} claimed
          </Badge>
          {hasReady && (
            <Badge tone="success" dot>
              Ready to claim
            </Badge>
          )}
          {endsSoon(campaign.campaign_ends_at) && (
            <Badge tone="warning" dot>
              Ending soon
            </Badge>
          )}
        </div>
      </header>

      <div>
        <h3>{campaign.campaign_name}</h3>
        <p className="card-meta">
          <Icon name="clock" size={14} />
          Ends {formatDateTime(campaign.campaign_ends_at)}
          {campaign.eta_minutes !== null && (
            <span className="meta-sep">·</span>
          )}
          {campaign.eta_minutes !== null && (
            <span>{formatEta(campaign.eta_minutes)} at current pace</span>
          )}
        </p>
      </div>

      <ul className="progress-drops">
        {campaign.drops.map((drop) => {
          const percent = clampPercent(drop.percent)
          const ready = drop.is_ready && !drop.is_claimed

          return (
            <li key={drop.drop_id} className="progress-drop">
              <div className="progress-drop-head">
                <strong>{drop.drop_name}</strong>
                <span className="muted">
                  {drop.current_minutes}/{drop.required_minutes} min
                </span>
              </div>

              <div
                className="progress-track"
                role="progressbar"
                aria-label={`${drop.drop_name} progress`}
                aria-valuenow={percent}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span
                  className={`progress-fill${ready ? ' ready' : ''}${
                    drop.is_claimed ? ' claimed' : ''
                  }`}
                  style={{ width: `${percent}%` }}
                />
              </div>

              <p className="progress-drop-eta">
                {formatRemaining(drop.remaining_minutes)} left
                {drop.rate_minutes_per_hour !== null && drop.eta_minutes !== null && (
                  <>
                    <span className="meta-sep">·</span>
                    {formatEta(drop.eta_minutes)} at current pace
                  </>
                )}
              </p>

              <div className="progress-drop-meta">
                {drop.is_claimed && <Badge tone="muted">Claimed</Badge>}
                {ready && (
                  <Badge tone="success" dot>
                    Ready
                  </Badge>
                )}
                {drop.benefits.length > 0 && (
                  <small className="muted">{drop.benefits.join(', ')}</small>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      {unclaimed.length > 0 && (
        <div className="card-footer">
          <a
            className="btn btn-secondary btn-sm"
            href="https://www.twitch.tv/drops/inventory"
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="external" size={14} />
            Open Twitch inventory
          </a>
        </div>
      )}
    </article>
  )
}
