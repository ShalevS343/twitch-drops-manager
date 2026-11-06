const DAY_MS = 24 * 60 * 60 * 1000

function formatDuration(minutes: number): string {
  const rounded = Math.max(0, Math.round(minutes))

  if (rounded < 60) {
    return `${rounded}m`
  }

  const hours = Math.floor(rounded / 60)
  const rest = rounded % 60
  return rest > 0 ? `${hours}h ${rest}m` : `${hours}h`
}

export function formatEta(minutes: number | null): string {
  if (minutes === null) return '—'
  return `~${formatDuration(minutes)}`
}

export function formatRemaining(minutes: number): string {
  return `${Math.max(0, Math.round(minutes))} min`
}

export function endsSoon(value: string | null): boolean {
  if (!value) return false

  const endsAt = new Date(value).getTime()
  if (Number.isNaN(endsAt)) return false

  const remaining = endsAt - Date.now()
  return remaining > 0 && remaining <= DAY_MS
}
