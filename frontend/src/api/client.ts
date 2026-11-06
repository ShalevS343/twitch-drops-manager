import type { Campaign, Game, ScanResult, Status, Stream } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = import.meta.env.VITE_API_TOKEN as string | undefined
  const headers = new Headers(init?.headers)

  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) {
    headers.set('X-API-Token', token)
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })

  if (!response.ok) {
    let detail = response.statusText
    const data = (await response.json().catch(() => null)) as { detail?: string } | null
    if (data?.detail) {
      detail = data.detail
    }
    throw new Error(detail)
  }

  return (await response.json()) as T
}

export const api = {
  status: () => request<Status>('/status'),
  games: () => request<Game[]>('/games'),
  campaigns: () => request<Campaign[]>('/campaigns'),
  streams: () => request<Stream[]>('/streams'),
  updateGames: (games: string[]) =>
    request<{ games: string[] }>('/games', {
      method: 'PUT',
      body: JSON.stringify({ games }),
    }),
  scan: () => request<ScanResult>('/scans', { method: 'POST' }),
  testTelegram: () => request<{ sent: boolean }>('/notifications/test', { method: 'POST' }),
}
