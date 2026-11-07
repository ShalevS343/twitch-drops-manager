import { useMemo, useState } from 'react'

import type { WatchQueueCampaign, WatchQueueItem } from '../api/types'
import { WatchFocusPanel } from '../components/WatchFocusPanel'
import { WatchQueueCard } from '../components/WatchQueueCard'
import { EmptyState } from '../components/ui/EmptyState'
import { Icon } from '../components/ui/Icon'
import { PerGameSelect } from '../components/ui/PerGameSelect'
import { LoadingState } from '../components/ui/Spinner'
import { useFocusWatcher, useWatcher, useWatchQueue } from '../hooks/useApi'
import { groupByGame, limitPerGame } from '../lib/streamGroups'

function openStream(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function WatchQueuePage() {
  const queueQuery = useWatchQueue()
  const watcher = useWatcher()
  const focus = useFocusWatcher()
  const items = useMemo(() => queueQuery.data ?? [], [queueQuery.data])
  const [perGame, setPerGame] = useState(5)

  const visibleItems = useMemo(
    () => limitPerGame(items, (item) => item.game_name, perGame),
    [items, perGame],
  )
  const groups = useMemo(
    () => groupByGame(visibleItems, (item) => item.game_name),
    [visibleItems],
  )

  const focusedCampaignId = watcher.data?.focus?.campaign_id ?? null
  const focusedStreamId = watcher.data?.focus?.stream_id ?? null

  function handleWatch(stream: WatchQueueItem, campaign: WatchQueueCampaign) {
    openStream(stream.url)
    focus.mutate({
      stream_id: stream.stream_id,
      campaign_id: campaign.campaign_id,
      strategy: 'manual',
    })
  }

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
              ? `${items.length} live stream${items.length === 1 ? '' : 's'} available${
                  perGame > 0 ? `; showing up to ${perGame} per game.` : '.'
                }`
              : 'Eligible live streams for your in-progress campaigns.'}
          </p>
        </div>
        <div className="inline-actions">
          <PerGameSelect value={perGame} onChange={setPerGame} />
          <a className="btn btn-ghost btn-sm" href="#/streams">
            View all live streams
            <Icon name="arrow-right" size={13} />
          </a>
        </div>
      </div>

      <WatchFocusPanel />

      {focus.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{focus.error.message}</span>
        </p>
      )}

      {items.length > 0 && (
        <div className="callout">
          <span className="callout-icon">
            <Icon name="target" size={20} />
          </span>
          <div className="callout-copy">
            <strong>Start watching a campaign</strong>
            <p>
              Pick a campaign below to open the live stream and start focus mode
              on that streamer.
            </p>
          </div>
        </div>
      )}

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
                  View live streams
                </a>
                <a className="btn btn-secondary" href="#/overview">
                  Back to overview
                </a>
              </div>
            }
          />
        </div>
      )}

      {groups.length > 0 && (
        <div className="game-groups">
          {groups.map((group) => (
            <section className="game-group" key={group.game}>
              <div className="game-group-head">
                <h3>{group.game}</h3>
                <span className="game-group-count">
                  {group.items.length} shown
                </span>
              </div>
              <div className="stream-grid">
                {group.items.map((item) => (
                  <WatchQueueCard
                    key={item.stream_id}
                    item={item}
                    onWatch={handleWatch}
                    activeCampaignId={focusedCampaignId}
                    activeStreamId={focusedStreamId}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
