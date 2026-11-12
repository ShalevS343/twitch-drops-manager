import type {
  AdminUser,
  AuthMe,
  AuthUser,
  Campaign,
  Game,
  ProgressCampaign,
  ProgressRefresh,
  ScanResult,
  Status,
  Stream,
  TwitchConnect,
  TwitchLoginResult,
  TwitchUserStatus,
  UpdateMeInput,
  WatchFocusInput,
  WatchQueueItem,
  WatchState,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let unauthorizedHandler: (() => void) | null = null

/**
 * Registers the callback used when the API reports an expired/missing session.
 * The auth provider uses it to clear caches and send the user back to the gate.
 */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null

  const prefix = `${name}=`
  const match = document.cookie
    .split(';')
    .map((row) => row.trim())
    .find((row) => row.startsWith(prefix))

  if (!match) return null

  const value = match.slice(prefix.length)
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers = new Headers(init?.headers)

  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCookie('tdm_csrf')
    if (csrf) {
      headers.set('X-CSRF-Token', csrf)
    }
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    let detail = response.statusText || `Request failed with status ${response.status}`
    const data = (await response.json().catch(() => null)) as
      | { detail?: unknown }
      | null

    if (typeof data?.detail === 'string' && data.detail.trim()) {
      detail = data.detail
    } else if (data?.detail) {
      detail = JSON.stringify(data.detail)
    }

    if (response.status === 401 && path !== '/auth/me') {
      unauthorizedHandler?.()
    }

    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const api = {
  authMe: () => request<AuthMe>('/auth/me'),
  twitchAuthorize: () => request<TwitchConnect>('/auth/twitch/authorize'),
  twitchConnect: (redirectUrl: string, inviteCode?: string) =>
    request<TwitchLoginResult>('/auth/twitch/connect', {
      method: 'POST',
      body: JSON.stringify({
        redirect_url: redirectUrl,
        ...(inviteCode ? { invite_code: inviteCode } : {}),
      }),
    }),
  logout: () => request<{ ok?: boolean }>('/auth/logout', { method: 'POST' }),
  updateMe: (input: UpdateMeInput) =>
    request<AuthUser>('/auth/me', {
      method: 'PATCH',
      body: JSON.stringify(input),
    }),
  twitchDisconnect: () =>
    request<{ disconnected: boolean }>('/auth/twitch/disconnect', { method: 'POST' }),

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
  progress: () => request<ProgressCampaign[]>('/progress'),
  refreshProgress: () => request<ProgressRefresh>('/progress/refresh', { method: 'POST' }),
  watchQueue: () => request<WatchQueueItem[]>('/watch-queue'),
  watcher: () => request<WatchState>('/watcher'),
  setWatcherEnabled: (enabled: boolean) =>
    request<WatchState>('/watcher', {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  focusWatcher: (input: WatchFocusInput) =>
    request<WatchState>('/watcher/focus', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  stopWatcher: () => request<WatchState>('/watcher', { method: 'DELETE' }),
  twitchStatus: () => request<TwitchUserStatus>('/twitch/status'),

  adminUsers: async () => {
    const data = await request<AdminUser[] | { users: AdminUser[] }>('/admin/users')
    return Array.isArray(data) ? data : data.users ?? []
  },
  setUserActive: (id: number, isActive: boolean) =>
    request<AdminUser>(`/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: isActive }),
    }),
}
