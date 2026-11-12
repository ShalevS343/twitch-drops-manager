import type { StatusQuery, TwitchStatusQuery } from '../hooks/useApi'
import {
  useCampaigns,
  useProgress,
  useRefreshProgress,
  useScan,
  useStreams,
  useWatchQueue,
} from '../hooks/useApi'
import { useAuth } from '../auth/AuthContext'
import {
  campaignPhase,
  inProgressDropCount,
  isProgressCampaignCompleted,
  progressPercent,
} from '../lib/campaigns'
import { endsSoon, formatRemaining, formatTimeUntil } from '../lib/format'
import type { ProgressCampaign } from '../api/types'
import { Badge } from '../components/ui/Badge'
import { EmptyState } from '../components/ui/EmptyState'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { StatCard } from '../components/ui/StatCard'

interface Props {
  status: StatusQuery
  twitch: TwitchStatusQuery
}

function MiniProgress({ campaign }: { campaign: ProgressCampaign }) {
  const percent = progressPercent(campaign)
  const completed = isProgressCampaignCompleted(campaign)

  return (
    <article className={`mini-progress${completed ? ' completed' : ''}`}>
      <div className="mini-progress-head">
        <div>
          <strong>{campaign.campaign_name}</strong>
          <span className="mini-progress-meta">
            {campaign.game_name || 'Unknown game'} · {campaign.claimed_count}/
            {campaign.total_count} claimed
          </span>
        </div>
        {completed ? (
          <Badge tone="success" dot>
            Completed
          </Badge>
        ) : (
          <Badge tone="accent">{percent}%</Badge>
        )}
      </div>
      <div className="progress-track">
        <span
          className={`progress-fill${percent >= 100 ? ' ready' : ''}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mini-progress-foot">
        <span>
          {completed
            ? 'All drops claimed'
            : `${formatRemaining(campaign.remaining_minutes)} left`}
        </span>
        <span>
          {completed ? 'Campaign complete' : `${inProgressDropCount(campaign)} drops open`}
        </span>
      </div>
    </article>
  )
}

export function OverviewPage({ status, twitch }: Props) {
  const { isAdmin } = useAuth()
  const campaignsQuery = useCampaigns()
  const progressQuery = useProgress()
  const streamsQuery = useStreams()
  const queueQuery = useWatchQueue()
  const scan = useScan()
  const refresh = useRefreshProgress()

  const campaigns = campaignsQuery.data ?? []
  const progress = progressQuery.data ?? []
  const streams = streamsQuery.data ?? []
  const queue = queueQuery.data ?? []
  const connected = twitch.data?.connected === true

  const activeCampaigns = campaigns.filter(
    (campaign) => campaignPhase(campaign) === 'active',
  ).length
  const dropsInProgress = progress.reduce(
    (sum, campaign) => sum + inProgressDropCount(campaign),
    0,
  )

  const readyDrops = progress.flatMap((campaign) =>
    campaign.drops
      .filter((drop) => drop.is_ready && !drop.is_claimed)
      .map((drop) => ({ campaign, drop })),
  )
  const readyCount = readyDrops.length

  const endingCampaigns = progress.filter(
    (campaign) =>
      endsSoon(campaign.campaign_ends_at) &&
      campaign.claimed_count < campaign.total_count,
  )

  const hasAttention = readyDrops.length > 0 || endingCampaigns.length > 0
  const topProgress = [...progress]
    .sort((a, b) => {
      const aCompleted = isProgressCampaignCompleted(a) ? 1 : 0
      const bCompleted = isProgressCampaignCompleted(b) ? 1 : 0
      if (aCompleted !== bCompleted) return aCompleted - bCompleted

      return a.remaining_minutes - b.remaining_minutes
    })
    .slice(0, 3)

  return (
    <div className="page">
      {!connected && !twitch.isLoading && (
        <div className="callout">
          <span className="callout-icon" aria-hidden="true">
            <Icon name="twitch" size={20} />
          </span>
          <div className="callout-copy">
            <strong>Connect your Twitch account</strong>
            <p>
              See how far along each drop is, get ready-to-claim alerts, and keep the
              watch queue accurate.
            </p>
          </div>
          <a className="btn btn-primary" href="#/profile">
            Connect Twitch
          </a>
        </div>
      )}

      <section className="stat-grid" aria-label="Dashboard summary">
        <StatCard
          label="Active campaigns"
          value={campaignsQuery.isLoading ? '—' : activeCampaigns}
          hint={`${campaigns.length || status.data?.campaign_count || 0} tracked total`}
          icon="gift"
          tone="accent"
        />
        <StatCard
          label="Drops in progress"
          value={progressQuery.isLoading ? '—' : dropsInProgress}
          hint={
            progress.length > 0
              ? `Across ${progress.length} campaign${progress.length === 1 ? '' : 's'}`
              : 'No open drops yet'
          }
          icon="chart"
          tone="accent"
        />
        <StatCard
          label="Live eligible streams"
          value={
            streamsQuery.isLoading
              ? status.data?.stream_count ?? '—'
              : streams.length
          }
          hint={`${status.data?.games_selected.length ?? 0} games selected`}
          icon="radio"
          tone="success"
        />
        <StatCard
          label="Ready to claim"
          value={progressQuery.isLoading ? '—' : readyCount}
          hint={readyCount > 0 ? 'Open Drops inventory' : 'Nothing waiting'}
          icon="sparkles"
          tone={readyCount > 0 ? 'success' : 'warning'}
        />
      </section>

      <div className="dashboard-grid">
        <section className="panel span-7" aria-labelledby="attention-title">
          <div className="section-head">
            <div>
              <h2 id="attention-title">
                <Icon name="alert" size={18} />
                Needs attention
              </h2>
              <p>Ready-to-claim drops and campaigns ending within 24 hours.</p>
            </div>
            {hasAttention && (
              <Badge tone="warning">{readyDrops.length + endingCampaigns.length}</Badge>
            )}
          </div>

          {progressQuery.isLoading ? (
            <LoadingState label="Checking drop progress…" />
          ) : hasAttention ? (
            <ul className="list">
              {readyDrops.slice(0, 4).map(({ campaign, drop }) => (
                <li className="list-item" key={`ready-${drop.drop_id}`}>
                  <div className="list-item-main">
                    <span className="list-item-title">{drop.drop_name}</span>
                    <span className="list-item-meta">
                      {campaign.campaign_name} · {drop.required_minutes} min complete
                    </span>
                  </div>
                  <div className="list-item-actions">
                    <Badge tone="success" dot>
                      Ready
                    </Badge>
                    <a
                      className="btn btn-secondary btn-sm"
                      href="https://www.twitch.tv/drops/inventory"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Claim on Twitch
                      <Icon name="external" size={13} />
                    </a>
                  </div>
                </li>
              ))}

              {endingCampaigns.slice(0, 4).map((campaign) => (
                <li className="list-item" key={`ending-${campaign.campaign_id}`}>
                  <div className="list-item-main">
                    <span className="list-item-title">{campaign.campaign_name}</span>
                    <span className="list-item-meta">
                      Ends {formatTimeUntil(campaign.campaign_ends_at)} ·{' '}
                      {campaign.claimed_count}/{campaign.total_count} claimed
                    </span>
                  </div>
                  <div className="list-item-actions">
                    <Badge tone="warning" dot>
                      Ending soon
                    </Badge>
                    <a className="btn btn-ghost btn-sm" href="#/progress">
                      View progress
                      <Icon name="arrow-right" size={13} />
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon="check"
              title="You're all caught up"
              message="No drops are ready to claim and no tracked campaigns end in the next 24 hours."
              compact
            />
          )}
        </section>

        <section className="panel span-5" aria-labelledby="queue-title">
          <div className="section-head">
            <div>
              <h2 id="queue-title">
                <Icon name="play" size={18} />
                Next in queue
              </h2>
              <p>Live streams that advance your open drops.</p>
            </div>
            <a className="btn btn-ghost btn-sm" href="#/watch-queue">
              Open watch queue
              <Icon name="arrow-right" size={13} />
            </a>
          </div>

          {queueQuery.isLoading ? (
            <LoadingState label="Loading watch queue…" />
          ) : queue.length === 0 ? (
            <EmptyState
              icon="radio"
              title="Queue is empty"
              message="No live streams match your in-progress campaigns right now."
              compact
            />
          ) : (
            <ul className="list">
              {queue.slice(0, 3).map((item) => {
                const nextCampaign = item.campaigns[0]
                return (
                  <li key={item.stream_id}>
                    <a
                      className="list-item list-item-link"
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <div className="list-item-main">
                        <span className="list-item-title">
                          {item.user_name || item.user_login}
                        </span>
                        <span className="list-item-meta">
                          {item.game_name || 'Unknown game'}
                          {nextCampaign?.next_drop_name
                            ? ` · Next: ${nextCampaign.next_drop_name}`
                            : ''}
                        </span>
                      </div>
                      <span className="list-item-trailing">
                        <Badge tone="live" dot>
                          Live
                        </Badge>
                        <span className="queue-watch">
                          Open stream
                          <Icon name="external" size={13} />
                        </span>
                      </span>
                    </a>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section className="panel span-7" aria-labelledby="progress-title">
          <div className="section-head">
            <div>
              <h2 id="progress-title">
                <Icon name="chart" size={18} />
                Campaign progress
              </h2>
              <p>A quick look at the campaigns closest to completion.</p>
            </div>
            <a className="btn btn-ghost btn-sm" href="#/progress">
              View all progress
              <Icon name="arrow-right" size={13} />
            </a>
          </div>

          {progressQuery.isLoading ? (
            <LoadingState label="Loading progress…" />
          ) : topProgress.length === 0 ? (
            <EmptyState
              icon="chart"
              title="No drops in progress"
              message={
                connected
                  ? 'Start watching a Drops-enabled stream on Twitch and sync your drop progress.'
                  : 'Connect Twitch to track your drop progress.'
              }
              compact
              action={
                !connected ? (
                  <a className="btn btn-secondary btn-sm" href="#/profile">
                    Connect Twitch
                  </a>
                ) : undefined
              }
            />
          ) : (
            <div className="mini-progress-list">
              {topProgress.map((campaign) => (
                <MiniProgress key={campaign.campaign_id} campaign={campaign} />
              ))}
            </div>
          )}
        </section>

        <section className="panel span-5" aria-labelledby="actions-title">
          <div className="section-head">
            <div>
              <h2 id="actions-title">
                <Icon name="sparkles" size={18} />
                Quick actions
              </h2>
              <p>
                {isAdmin
                  ? 'Scan for campaigns and streams, or sync your drop progress.'
                  : 'Sync your drop progress or manage the games you track.'}
              </p>
            </div>
          </div>

          <div className="quick-actions">
            {isAdmin && (
              <button
                className="btn btn-primary"
                onClick={() => scan.mutate()}
                disabled={scan.isPending}
              >
                <Icon name="scan" size={16} />
                {scan.isPending ? 'Scanning…' : 'Scan for new drops'}
              </button>
            )}
            <button
              className="btn btn-secondary"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending || !connected}
              title={
                connected
                  ? 'Sync your Twitch drop progress'
                  : 'Connect Twitch to sync drop progress'
              }
            >
              <Icon name="refresh" size={16} />
              {refresh.isPending ? 'Syncing…' : 'Sync drop progress'}
            </button>
            <a className="btn btn-ghost" href="#/settings">
              <Icon name="settings" size={16} />
              Manage tracked games
            </a>
            <a
              className="btn btn-ghost"
              href="https://www.twitch.tv/drops/inventory"
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="external" size={16} />
              Open Drops inventory
            </a>
          </div>

          {!connected && !twitch.isLoading && (
            <p className="muted small">
              Sync drop progress is available after connecting Twitch.
            </p>
          )}

          {isAdmin && scan.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{scan.error.message}</span>
            </p>
          )}
          {isAdmin && scan.data && (
            <p className="alert alert-success" role="status">
              <Icon name="check" size={16} />
              <span>
                Found {scan.data.campaign_count} campaigns, {scan.data.stream_count}{' '}
                streams, {scan.data.notified_count} notifications.
              </span>
            </p>
          )}
          {refresh.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{refresh.error.message}</span>
            </p>
          )}
          {refresh.data && !refresh.data.connected && (
            <p className="alert alert-warning" role="alert">
              <Icon name="alert" size={16} />
              <span>
                Twitch reconnect required before drop progress can sync.
              </span>
            </p>
          )}
          {refresh.data?.connected && (
            <p className="alert alert-success" role="status">
              <Icon name="check" size={16} />
              <span>
                Synced {refresh.data.drop_count} drops from{' '}
                {refresh.data.campaign_count} campaign(s).
              </span>
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
