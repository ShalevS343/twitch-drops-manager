import { CampaignCard } from './components/CampaignCard'
import { GameSelector } from './components/GameSelector'
import { StatusPanel } from './components/StatusPanel'
import { StreamCard } from './components/StreamCard'
import { useCampaigns, useGames, useStatus, useStreams } from './hooks/useApi'

export default function App() {
  const status = useStatus()
  const games = useGames()
  const campaigns = useCampaigns()
  const streams = useStreams()

  return (
    <main className="app">
      <header>
        <h1>Twitch Drops Manager</h1>
        <p className="muted">Track active drops and live eligible streams.</p>
      </header>

      <StatusPanel status={status.data} isLoading={status.isLoading} error={status.error} />

      <GameSelector games={games.data ?? []} isLoading={games.isLoading} />

      <section>
        <h2>
          Campaigns <span className="muted">({campaigns.data?.length ?? 0})</span>
        </h2>
        {campaigns.isLoading && <p className="muted">Loading campaigns…</p>}
        {campaigns.error && <p className="error">{campaigns.error.message}</p>}
        {campaigns.data?.length === 0 && (
          <p className="muted">No campaigns cached yet. Run a scan.</p>
        )}
        <div className="grid">
          {campaigns.data?.map((campaign) => (
            <CampaignCard key={campaign.id} campaign={campaign} />
          ))}
        </div>
      </section>

      <section>
        <h2>
          Live Streams <span className="muted">({streams.data?.length ?? 0})</span>
        </h2>
        {streams.isLoading && <p className="muted">Loading streams…</p>}
        {streams.error && <p className="error">{streams.error.message}</p>}
        {streams.data?.length === 0 && (
          <p className="muted">No matching live streams right now.</p>
        )}
        <div className="grid">
          {streams.data?.map((stream) => (
            <StreamCard key={stream.id} stream={stream} />
          ))}
        </div>
      </section>
    </main>
  )
}
