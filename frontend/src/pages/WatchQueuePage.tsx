import { useMemo, useState } from 'react'

import type { WatchQueueCampaign, WatchQueueItem } from '../api/types'
import { WatchFocusPanel } from '../components/WatchFocusPanel'
import { WatchQueueCard } from '../components/WatchQueueCard'
import { WatchSessionPanel } from '../components/WatchSessionPanel'
import { EmptyState } from '../components/ui/EmptyState'
import { Icon } from '../components/ui/Icon'
import { PerGameSelect } from '../components/ui/PerGameSelect'
import { LoadingState } from '../components/ui/Spinner'
import { useWatchQueue } from '../hooks/useApi'
import { useWatchSession } from '../hooks/useWatchSession'
import { groupByGame, limitPerGame } from '../lib/streamGroups'
import { suggestNextCampaigns } from '../lib/watchQueue'
import type { WatchSuggestion } from '../lib/watchQueue'

function openStream(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function WatchQueuePage() {
  const queueQuery = useWatchQueue()
  const items = useMemo(() => queueQuery.data ?? [], [queueQuery.data])
  const watch = useWatchSession()
  const session = watch.session
  const [perGame, setPerGame] = useState(5)

  const visibleItems = useMemo(
    () => limitPerGame(items, (item) => item.game_name, perGame),
    [items, perGame],
  )
  const groups = useMemo(
    () => groupByGame(visibleItems, (item) => item.game_name),
    [visibleItems],
  )

  const suggestions = useMemo(
    () => suggestNextCampaigns(items, session?.campaignId ?? null),
    [items, session?.campaignId],
  )

  function startSession(stream: WatchQueueItem, campaign: WatchQueueCampaign) {
    watch.start({
      streamId: stream.stream_id,
      userLogin: stream.user_login,
      userName: stream.user_name,
      streamUrl: stream.url,
      streamTitle: stream.title,
      gameName: stream.game_name,
      campaignId: campaign.campaign_id,
      campaignName: campaign.campaign_name,
      targetMinutes: campaign.remaining_minutes,
    })
    openStream(stream.url)
  }

  function handleWatch(stream: WatchQueueItem, campaign: WatchQueueCampaign) {
    if (session) {
      return
    }
    startSession(stream, campaign)
  }

  function handleSwitch(suggestion: WatchSuggestion) {
    startSession(suggestion.stream, suggestion.campaign)
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

      {session && (
        <WatchSessionPanel
          session={session}
          elapsedMs={watch.elapsedMs}
          isRunning={watch.isRunning}
          suggestions={suggestions}
          onPause={watch.pause}
          onResume={watch.resume}
          onStop={watch.stop}
          onSwitch={handleSwitch}
        />
      )}

      {!session && items.length > 0 && (
        <div className="callout">
          <span className="callout-icon">
            <Icon name="clock" size={20} />
          </span>
          <div className="callout-copy">
            <strong>Watch one campaign at a time</strong>
            <p>
              Pick a campaign below to start a timer and open the stream. Only
              one session runs at a time.
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
                    activeCampaignId={session?.campaignId ?? null}
                    activeStreamId={session?.streamId ?? null}
                    sessionActive={session !== null}
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
