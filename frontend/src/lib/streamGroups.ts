export interface GameGroup<T> {
  game: string
  items: T[]
}

/**
 * Keep at most `perGame` items for each game, preserving the original order.
 * `perGame <= 0` disables the limit.
 */
export function limitPerGame<T>(
  items: T[],
  gameOf: (item: T) => string,
  perGame: number,
): T[] {
  if (perGame <= 0) {
    return items
  }

  const counts = new Map<string, number>()
  const limited: T[] = []

  for (const item of items) {
    const game = gameOf(item) || 'Unknown game'
    const count = counts.get(game) ?? 0
    if (count >= perGame) {
      continue
    }

    counts.set(game, count + 1)
    limited.push(item)
  }

  return limited
}

/** Group items by game, preserving the order in which each game first appears. */
export function groupByGame<T>(
  items: T[],
  gameOf: (item: T) => string,
): GameGroup<T>[] {
  const groups = new Map<string, T[]>()

  for (const item of items) {
    const game = gameOf(item) || 'Unknown game'
    const group = groups.get(game)
    if (group) {
      group.push(item)
    } else {
      groups.set(game, [item])
    }
  }

  return [...groups.entries()].map(([game, groupItems]) => ({
    game,
    items: groupItems,
  }))
}
