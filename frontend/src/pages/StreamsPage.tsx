import { useMemo, useState } from 'react'

import { StreamCard } from '../components/StreamCard'
import { Badge } from '../components/ui/Badge'
import { EmptyState } from '../components/ui/EmptyState'
import { Icon } from '../components/ui/Icon'
import { LoadingState } from '../components/ui/Spinner'
import { useStreams } from '../hooks/useApi'

export function StreamsPage() {
  const streamsQuery = useStreams()
  const [search, setSearch] = useState('')
  const [game, setGame] = useState('all')
  const [language, setLanguage] = useState('all')

  const streams = streamsQuery.data ?? []

  const games = useMemo(() => {
    const names = new Set(streams.map((stream) => stream.game.name))
    return [...names].sort((a, b) => a.localeCompare(b))
  }, [streams])

  const languages = useMemo(() => {
    const values = new Set(
      streams.map((stream) => stream.language).filter((value) => Boolean(value)),
    )
    return [...values].sort((a, b) => a.localeCompare(b))
  }, [streams])

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()

    return streams.filter((stream) => {
      const matchesSearch =
        !query ||
        stream.title.toLowerCase().includes(query) ||
        stream.user_name.toLowerCase().includes(query) ||
        stream.user_login.toLowerCase().includes(query) ||
        stream.game.name.toLowerCase().includes(query)

      const matchesGame = game === 'all' || stream.game.name === game
      const matchesLanguage = language === 'all' || stream.language === language

      return matchesSearch && matchesGame && matchesLanguage
    })
  }, [game, language, search, streams])

  const hasFilters = Boolean(search.trim()) || game !== 'all' || language !== 'all'

  function clearFilters() {
    setSearch('')
    setGame('all')
    setLanguage('all')
  }

  return (
    <div className="page">
      <div className="toolbar" role="search" aria-label="Filter live streams">
        <label className="search-field">
          <span className="sr-only">Search live streams</span>
          <Icon name="search" size={16} />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search streams, channels, or games…"
            aria-label="Search live streams"
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
          <span className="sr-only">Filter by language</span>
          <select
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
          >
            <option value="all">All languages</option>
            {languages.map((value) => (
              <option key={value} value={value}>
                {value}
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
          <Badge tone="live" dot>
            Live
          </Badge>{' '}
          Showing <strong>{filtered.length}</strong> of{' '}
          <strong>{streams.length}</strong> streams
        </span>
        {hasFilters && <Badge tone="accent">Filtered</Badge>}
      </div>

      {streamsQuery.isLoading && <LoadingState label="Loading live streams…" />}

      {streamsQuery.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{streamsQuery.error.message}</span>
        </p>
      )}

      {!streamsQuery.isLoading && streams.length === 0 && (
        <div className="panel">
          <EmptyState
            icon="radio"
            title="No live streams right now"
            message="No live Drops-enabled streams match your selected games. Try again later or adjust your game whitelist."
            action={
              <a className="btn btn-secondary" href="#/settings">
                <Icon name="settings" size={16} />
                Manage games
              </a>
            }
          />
        </div>
      )}

      {streams.length > 0 && filtered.length === 0 && (
        <div className="panel">
          <EmptyState
            icon="search"
            title="No streams match these filters"
            message="Try a different search term, game, or language."
            action={
              <button className="btn btn-secondary" onClick={clearFilters}>
                Clear filters
              </button>
            }
          />
        </div>
      )}

      {filtered.length > 0 && (
        <div className="stream-grid">
          {filtered.map((stream) => (
            <StreamCard key={stream.id} stream={stream} />
          ))}
        </div>
      )}
    </div>
  )
}
