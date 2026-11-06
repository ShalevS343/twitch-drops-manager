import type { Campaign } from '../api/types'

export function CampaignCard({ campaign }: { campaign: Campaign }) {
  return (
    <article className="card">
      <header>
        <span className="badge">{campaign.game.name}</span>
        <span className={`badge ${campaign.status === 'ACTIVE' ? 'active' : ''}`}>
          {campaign.status || 'UNKNOWN'}
        </span>
      </header>

      <h3>{campaign.name}</h3>
      <p className="muted">Publisher: {campaign.owner_name || 'Unknown'}</p>
      <p className="muted">Ends: {campaign.ends_at ?? 'Unknown'}</p>

      <ul className="rewards">
        {campaign.rewards.map((reward) => (
          <li key={reward.id}>
            <strong>{reward.name}</strong>
            <span>{reward.required_minutes} min</span>
            {reward.benefit_name && <small>{reward.benefit_name}</small>}
          </li>
        ))}
      </ul>

      {campaign.details_url && (
        <a href={campaign.details_url} target="_blank" rel="noreferrer">
          Campaign details
        </a>
      )}
    </article>
  )
}
