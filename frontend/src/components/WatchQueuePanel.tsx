import type { WatchQueueItem } from '../api/types'
import { useWatchQueue } from '../hooks/useApi'
import { endsSoon, formatEta, formatRemaining } from '../lib/format'

function WatchQueueCard({ item }: { item: WatchQueueItem }) {
  const hasEndingSoon = item.campaigns.some((campaign) => endsSoon(campaign.ends_at))

  return (
    <article className="card">
      <header>
        <span className="badge">{item.game_name || 'Unknown game'}</span>
        <span className="badge active">LIVE</span>
        {hasEndingSoon && <span className="badge ending-soon">Ends soon</span>}
      </header>

      <h3>{item.user_name || item.user_login}</h3>
      <p>{item.title}</p>
      <p className="muted">
        {item.viewers.toLocaleString()} viewers · {item.language || 'unknown lang'}
      </p>

      <ul className="watch-queue-campaigns">
        {item.campaigns.map((campaign) => {
          const remainingMinutes =
            campaign.next_drop_remaining_minutes ?? campaign.remaining_minutes

          return (
            <li className="watch-queue-chip" key={campaign.campaign_id}>
              <div className="watch-queue-chip-head">
                <strong>{campaign.campaign_name}</strong>
              </div>
              <span className="watch-queue-chip-next">
                {campaign.next_drop_name
                  ? `Next drop: ${campaign.next_drop_name}`
                  : 'No upcoming drop'}
              </span>
              <span className="watch-queue-chip-meta">
                {formatRemaining(remainingMinutes)} left · ETA{' '}
                {formatEta(campaign.eta_minutes)}
              </span>
            </li>
          )
        })}
      </ul>

      <a href={item.url} target="_blank" rel="noreferrer">
        Watch
      </a>
    </article>
  )
}

export function WatchQueuePanel() {
  const queue = useWatchQueue()
  const items = queue.data ?? []

  return (
    <section className="panel">
      <h2>
        Watch Queue <span className="muted">({items.length})</span>
      </h2>

      {queue.isLoading && <p className="muted">Loading watch queue…</p>}
      {queue.error && <p className="error">{queue.error.message}</p>}
      {!queue.isLoading && !queue.error && items.length === 0 && (
        <p className="muted">No live streams for your in-progress campaigns right now.</p>
      )}

      {items.length > 0 && (
        <div className="grid">
          {items.map((item) => (
            <WatchQueueCard key={item.stream_id} item={item} />
          ))}
        </div>
      )}
    </section>
  )
}
