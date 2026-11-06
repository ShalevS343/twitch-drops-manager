import type { Stream } from '../api/types'

export function StreamCard({ stream }: { stream: Stream }) {
  return (
    <article className="card">
      <header>
        <span className="badge">{stream.game.name}</span>
        <span className="badge active">LIVE</span>
      </header>

      <h3>{stream.user_name || stream.user_login}</h3>
      <p>{stream.title}</p>
      <p className="muted">
        {stream.viewers.toLocaleString()} viewers · {stream.language || 'unknown lang'}
      </p>
      <p className="muted">Campaigns: {stream.matching_campaigns.join(', ') || '—'}</p>

      <a href={stream.url} target="_blank" rel="noreferrer">
        Open stream
      </a>
    </article>
  )
}
