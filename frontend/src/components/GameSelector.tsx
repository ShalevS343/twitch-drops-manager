import { useEffect, useState } from 'react'

import type { Game } from '../api/types'
import { useSaveGames } from '../hooks/useApi'

interface Props {
  games: Game[]
  isLoading: boolean
}

export function GameSelector({ games, isLoading }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const save = useSaveGames()

  useEffect(() => {
    setSelected(new Set(games.filter((game) => game.selected).map((game) => game.name)))
  }, [games])

  function toggle(name: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(name)) {
        next.delete(name)
      } else {
        next.add(name)
      }
      return next
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

      <div className="game-grid">
        {games.map((game) => (
          <label key={game.id} className="game">
            <input
              type="checkbox"
              checked={selected.has(game.name)}
              onChange={() => toggle(game.name)}
            />
            <span>{game.name}</span>
            <small className="muted">{game.campaign_count}</small>
          </label>
        ))}
      </div>

      <button onClick={() => save.mutate([...selected])} disabled={save.isPending}>
        {save.isPending ? 'Saving…' : 'Save selection'}
      </button>

      {save.error && <p className="error">{save.error.message}</p>}
      {save.isSuccess && <p className="success">Saved.</p>}
    </section>
  )
}
