import { WatchQueueCard } from '../components/WatchQueueCard'
import { EmptyState } from '../components/ui/EmptyState'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { useWatchQueue } from '../hooks/useApi'

export function WatchQueuePage() {
  const queueQuery = useWatchQueue()
  const items = queueQuery.data ?? []

  return (
    <div className="page">
      <div className="section-head">
        <div>
          <h2>
            <Icon name="play" size={18} />
            Watch queue
          </h2>
          <p>
            {items.length > 0
              ? `${items.length} live stream${items.length === 1 ? '' : 's'} ready to advance your open drops.`
              : 'Eligible live streams for your in-progress campaigns.'}
          </p>
        </div>
        <a className="btn btn-ghost btn-sm" href="#/streams">
          Browse all streams
          <Icon name="arrow-right" size={13} />
        </a>
      </div>

      {queueQuery.isLoading && <LoadingState label="Loading watch queue…" />}

      {queueQuery.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{queueQuery.error.message}</span>
        </p>
      )}

      {!queueQuery.isLoading && !queueQuery.error && items.length === 0 && (
        <div className="panel">
          <EmptyState
            icon="radio"
            title="Your watch queue is empty"
            message="There are no live streams matching your in-progress campaigns right now. Check the live streams page or run a scan."
            action={
              <div className="inline-actions">
                <a className="btn btn-primary" href="#/streams">
                  <Icon name="radio" size={16} />
                  Browse live streams
                </a>
                <a className="btn btn-secondary" href="#/overview">
                  Back to overview
                </a>
              </div>
            }
          />
        </div>
      )}

      {items.length > 0 && (
        <div className="stream-grid">
          {items.map((item) => (
            <WatchQueueCard key={item.stream_id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
