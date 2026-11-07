import { useMemo, useState } from 'react'

import { CampaignCard } from '../components/CampaignCard'
import { Badge } from '../components/ui/Badge'
import { EmptyState } from '../components/ui/EmptyState'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { useCampaigns, useProgress, useScan } from '../hooks/useApi'
import {
  campaignGqlId,
  campaignPhase,
  isProgressCampaignCompleted,
  type CampaignPhase,
} from '../lib/campaigns'

type StatusFilter = 'all' | 'active' | 'upcoming' | 'ended'

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All statuses' },
  { value: 'active', label: 'Active' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'ended', label: 'Ended' },
]

export function CampaignsPage() {
  const campaignsQuery = useCampaigns()
  const progressQuery = useProgress()
  const scan = useScan()

  const [search, setSearch] = useState('')
  const [game, setGame] = useState('all')
  const [status, setStatus] = useState<StatusFilter>('all')

  const campaigns = campaignsQuery.data ?? []
  const progress = progressQuery.data ?? []

  const completedIds = useMemo(
    () =>
      new Set(
        progress
          .filter(isProgressCampaignCompleted)
          .map((campaign) => campaign.campaign_id),
      ),
    [progress],
  )

  const games = useMemo(() => {
    const names = new Set(campaigns.map((campaign) => campaign.game.name))
    return [...names].sort((a, b) => a.localeCompare(b))
  }, [campaigns])

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()

    return campaigns
      .filter((campaign) => {
        const phase: CampaignPhase = campaignPhase(campaign)
        const matchesSearch =
          !query ||
          campaign.name.toLowerCase().includes(query) ||
          campaign.game.name.toLowerCase().includes(query) ||
          campaign.owner_name.toLowerCase().includes(query)

        const matchesGame = game === 'all' || campaign.game.name === game
        const matchesStatus = status === 'all' || phase === status

        return matchesSearch && matchesGame && matchesStatus
      })
      .sort((a, b) => {
        const aCompleted = completedIds.has(campaignGqlId(a.external_id)) ? 1 : 0
        const bCompleted = completedIds.has(campaignGqlId(b.external_id)) ? 1 : 0
        return aCompleted - bCompleted
      })
  }, [campaigns, completedIds, game, search, status])

  const hasFilters = Boolean(search.trim()) || game !== 'all' || status !== 'all'

  function clearFilters() {
    setSearch('')
    setGame('all')
    setStatus('all')
  }

  return (
    <div className="page">
      <div className="toolbar" role="search" aria-label="Filter campaigns">
        <label className="search-field">
          <span className="sr-only">Search campaigns</span>
          <Icon name="search" size={16} />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search campaigns, games, or publishers…"
            aria-label="Search campaigns"
          />
        </label>

        <label className="select-field">
          <span className="sr-only">Filter by game</span>
          <select value={game} onChange={(event) => setGame(event.target.value)}>
            <option value="all">All games</option>
            {games.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="select-field">
          <span className="sr-only">Filter by status</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as StatusFilter)}
          >
            {STATUS_FILTERS.map((filter) => (
              <option key={filter.value} value={filter.value}>
                {filter.label}
              </option>
            ))}
          </select>
        </label>

        {hasFilters && (
          <button type="button" className="btn btn-ghost" onClick={clearFilters}>
            <Icon name="x" size={14} />
            Clear filters
          </button>
        )}
      </div>

      <div className="results-bar">
        <span>
          Showing <strong>{filtered.length}</strong> of{' '}
          <strong>{campaigns.length}</strong> campaigns
        </span>
        {hasFilters && <Badge tone="accent">Filtered</Badge>}
      </div>

      {campaignsQuery.isLoading && <LoadingState label="Loading campaigns…" />}

      {campaignsQuery.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{campaignsQuery.error.message}</span>
        </p>
      )}

      {scan.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{scan.error.message}</span>
        </p>
      )}

      {!campaignsQuery.isLoading && campaigns.length === 0 && (
        <div className="panel">
          <EmptyState
            icon="gift"
            title="No campaigns cached yet"
            message="Run a scan to fetch the latest Twitch Drops campaigns for your selected games."
            action={
              <button
                className="btn btn-primary"
                onClick={() => scan.mutate()}
                disabled={scan.isPending}
              >
                <Icon name="scan" size={16} />
                {scan.isPending ? 'Scanning…' : 'Scan for new drops'}
              </button>
            }
          />
        </div>
      )}

      {!campaignsQuery.isLoading && campaigns.length > 0 && filtered.length === 0 && (
        <div className="panel">
          <EmptyState
            icon="search"
            title="No campaigns match these filters"
            message="Try a different search term, game, or status."
            action={
              <button className="btn btn-secondary" onClick={clearFilters}>
                Clear filters
              </button>
            }
          />
        </div>
      )}

      {filtered.length > 0 && (
        <div className="campaign-grid">
          {filtered.map((campaign) => (
            <CampaignCard
              key={campaign.id}
              campaign={campaign}
              completed={completedIds.has(campaignGqlId(campaign.external_id))}
            />
          ))}
        </div>
      )}
    </div>
  )
}
