const DAY_MS = 24 * 60 * 60 * 1000

export function formatRemaining(minutes: number): string {
  return `${Math.max(0, Math.round(minutes))} min`
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Unknown'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatTimeUntil(value: string | null | undefined): string {
  if (!value) return 'Unknown'

  const remaining = new Date(value).getTime() - Date.now()
  if (Number.isNaN(remaining)) return 'Unknown'
  if (remaining <= 0) return 'Ended'

  const minutes = Math.ceil(remaining / 60_000)
  if (minutes < 60) return `in ${minutes}m`

  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours < 24) return rest > 0 ? `in ${hours}h ${rest}m` : `in ${hours}h`

  const days = Math.floor(hours / 24)
  const restHours = hours % 24
  return restHours > 0 ? `in ${days}d ${restHours}h` : `in ${days}d`
}

export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value === 0) return '0s'
  if (value % 3600 === 0) return `${value / 3600}h`
  if (value % 60 === 0) return `${value / 60}m`
  return `${value}s`
}

export function endsSoon(value: string | null | undefined): boolean {
  if (!value) return false

  const endsAt = new Date(value).getTime()
  if (Number.isNaN(endsAt)) return false

  const remaining = endsAt - Date.now()
  return remaining > 0 && remaining <= DAY_MS
}

export function titleCase(value: string | null | undefined): string {
  const normalized = value?.trim()
  if (!normalized) return 'Unknown'
  return normalized.charAt(0).toUpperCase() + normalized.slice(1).toLowerCase()
}
