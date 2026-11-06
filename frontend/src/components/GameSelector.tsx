import { useEffect, useMemo, useState } from 'react'

import type { Game } from '../api/types'
import { useSaveGames } from '../hooks/useApi'

interface Props {
  games: Game[]
  isLoading: boolean
}

function selectedNames(games: Game[]): Set<string> {
  return new Set(games.filter((game) => game.selected).map((game) => game.name))
}

function sameNames(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) {
    return false
  }
  for (const name of a) {
    if (!b.has(name)) {
      return false
    }
  }
  return true
}

export function GameSelector({ games, isLoading }: Props) {
  const [selected, setSelected] = useState<Set<string>>(() => selectedNames(games))
  const [saved, setSaved] = useState<Set<string>>(() => selectedNames(games))
  const [search, setSearch] = useState('')
  const save = useSaveGames()

  useEffect(() => {
    const names = selectedNames(games)
    setSelected(names)
    setSaved(names)
  }, [games])

  const gamesByName = useMemo(() => {
    const map = new Map<string, Game>()
    for (const game of games) {
      map.set(game.name, game)
    }
    return map
  }, [games])

  const matches = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) {
      return games
    }
    return games.filter((game) => game.name.toLowerCase().includes(query))
  }, [games, search])

  const results = useMemo(
    () => matches.filter((game) => !selected.has(game.name)),
    [matches, selected],
  )

  const dirty = !sameNames(selected, saved)

  function add(name: string) {
    setSelected((current) => {
      const next = new Set(current)
      next.add(name)
      return next
    })
  }

  function remove(name: string) {
    setSelected((current) => {
      const next = new Set(current)
      next.delete(name)
      return next
    })
  }

  function saveSelection() {
    const names = [...selected]
    save.mutate(names, {
      onSuccess: () => setSaved(new Set(names)),
    })
  }

  if (isLoading) {
    return (
      <section className="panel">
        <p className="muted">Loading games…</p>
      </section>
    )
  }

  if (games.length === 0) {
    return (
      <section className="panel">
        <p className="muted">No games cached yet. Run a scan to load available games.</p>
      </section>
    )
  }

  return (
    <section className="panel">
      <h2>Game whitelist</h2>
      <p className="muted">Only campaigns for selected games are tracked and scanned.</p>

      <div className="whitelist-selected">
        <div className="section-label">
          <span>Selected</span>
          <small className="muted">{selected.size}</small>
        </div>

        {selected.size === 0 ? (
          <p className="empty-note">No games selected. Search below to add games.</p>
        ) : (
          <div className="chip-list">
            {[...selected]
              .sort((a, b) => a.localeCompare(b))
              .map((name) => {
                const game = gamesByName.get(name)
                return (
                  <span key={name} className="chip">
                    <span>{name}</span>
                    {game && (
                      <small title={`${game.campaign_count} campaigns`}>
                        {game.campaign_count}
                      </small>
                    )}
                    <button
                      type="button"
                      onClick={() => remove(name)}
                      aria-label={`Remove ${name} from whitelist`}
                    >
                      ×
                    </button>
                  </span>
                )
              })}
          </div>
        )}
      </div>

      <div className="search-row">
        <input
          className="search-input"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search games…"
          aria-label="Search games"
        />
        {search && (
          <button type="button" className="secondary" onClick={() => setSearch('')}>
            Clear
          </button>
        )}
      </div>

      <div className="section-label">
        <span>{search ? 'Search results' : 'Available games'}</span>
        <small className="muted">{results.length}</small>
      </div>

      <div className="game-list">
        {results.length === 0 ? (
          <p className="empty-note">
            {matches.length > 0
              ? 'All matching games are already selected.'
              : search
                ? `No games match “${search}”.`
                : 'All available games are already selected.'}
          </p>
        ) : (
          results.map((game) => (
            <button
              key={game.id}
              type="button"
              className="game-option"
              onClick={() => add(game.name)}
            >
              <span>{game.name}</span>
              <small className="muted">
                {game.campaign_count} {game.campaign_count === 1 ? 'campaign' : 'campaigns'}
              </small>
              <span className="add-mark">+</span>
            </button>
          ))
        )}
      </div>

      <div className="whitelist-footer">
        <button onClick={saveSelection} disabled={!dirty || save.isPending}>
          {save.isPending ? 'Saving…' : 'Save selection'}
        </button>
        {dirty && <span className="muted">Unsaved changes</span>}
        {save.error && <span className="error">{save.error.message}</span>}
        {!dirty && save.isSuccess && <span className="success">Saved.</span>}
      </div>
    </section>
  )
}
