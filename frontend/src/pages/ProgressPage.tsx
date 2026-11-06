import { ProgressCard } from '../components/ProgressCard'
import { TwitchConnect, useTwitchConnect } from '../components/TwitchConnect'
import { EmptyState } from '../components/ui/EmptyState'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { useProgress, useRefreshProgress, type TwitchStatusQuery } from '../hooks/useApi'

interface Props {
  twitch: TwitchStatusQuery
}

export function ProgressPage({ twitch }: Props) {
  const progressQuery = useProgress()
  const refresh = useRefreshProgress()
  const connect = useTwitchConnect()

  const connected = twitch.data?.connected === true
  const progress = progressQuery.data ?? []

  if (twitch.isLoading) {
    return <LoadingState label="Loading Twitch connection…" />
  }

  return (
    <div className="page">
      {twitch.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{twitch.error.message}</span>
        </p>
      )}

      {!connected && (
        <section className="panel connect-panel">
          <div className="connect-hero">
            <span className="connect-hero-icon" aria-hidden="true">
              <Icon name="twitch" size={26} />
            </span>
            <div className="connect-hero-copy">
              <h2>Connect Twitch to see your drop progress</h2>
              <p>
                Progress, ETA, and ready-to-claim status come directly from your Twitch
                account. This app never claims rewards for you.
              </p>
            </div>
            <button
              className="btn btn-primary"
              onClick={connect.start}
              disabled={connect.starting}
            >
              <Icon name="twitch" size={16} />
              {connect.starting ? 'Starting…' : 'Connect Twitch'}
            </button>
          </div>
          <TwitchConnect connect={connect} />
        </section>
      )}

      {connected && (
        <>
          <div className="section-head">
            <div>
              <h2>
                <Icon name="chart" size={18} />
                Campaign progress
              </h2>
              <p>
                Connected as{' '}
                <strong>
                  {twitch.data?.display_name || twitch.data?.login || 'Twitch user'}
                </strong>
                . Updated automatically every few minutes.
              </p>
            </div>
            <button
              className="btn btn-secondary"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
            >
              <Icon name="refresh" size={16} />
              {refresh.isPending ? 'Refreshing…' : 'Refresh progress'}
            </button>
          </div>

          {refresh.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{refresh.error.message}</span>
            </p>
          )}
          {refresh.data && (
            <p className="alert alert-success" role="status">
              <Icon name="check" size={16} />
              <span>
                Synced {refresh.data.drop_count} drops from{' '}
                {refresh.data.campaign_count} campaign(s).
              </span>
            </p>
          )}

          {progressQuery.isLoading && <LoadingState label="Loading drop progress…" />}

          {progressQuery.error && (
            <p className="alert alert-danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{progressQuery.error.message}</span>
            </p>
          )}

          {!progressQuery.isLoading && !progressQuery.error && progress.length === 0 && (
            <div className="panel">
              <EmptyState
                icon="chart"
                title="No drops in progress yet"
                message="Start watching a Drops-enabled stream on Twitch, then refresh progress."
                action={
                  <div className="inline-actions">
                    <button
                      className="btn btn-secondary"
                      onClick={() => refresh.mutate()}
                      disabled={refresh.isPending}
                    >
                      <Icon name="refresh" size={16} />
                      Refresh progress
                    </button>
                    <a
                      className="btn btn-ghost"
                      href="https://www.twitch.tv/directory"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Browse Twitch
                      <Icon name="external" size={14} />
                    </a>
                  </div>
                }
              />
            </div>
          )}

          {progress.length > 0 && (
            <div className="campaign-grid">
              {progress.map((campaign) => (
                <ProgressCard key={campaign.campaign_id} campaign={campaign} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
