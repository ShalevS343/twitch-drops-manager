import { useCallback, useEffect, useMemo, useState } from 'react'

export const WATCH_SESSION_STORAGE_KEY = 'tdm.watch-session.v1'

const STALE_AFTER_MS = 7 * 24 * 60 * 60 * 1000

export interface WatchSession {
  streamId: number
  userLogin: string
  userName: string
  streamUrl: string
  streamTitle: string
  gameName: string
  campaignId: string
  campaignName: string
  targetMinutes: number
  startedAt: number
  accumulatedMs: number
  resumedAt: number | null
}

export type WatchSessionStart = Omit<
  WatchSession,
  'startedAt' | 'accumulatedMs' | 'resumedAt'
>

function isWatchSession(value: unknown): value is WatchSession {
  if (!value || typeof value !== 'object') {
    return false
  }

  const record = value as Record<string, unknown>
  return (
    typeof record.streamId === 'number' &&
    typeof record.userLogin === 'string' &&
    typeof record.userName === 'string' &&
    typeof record.streamUrl === 'string' &&
    typeof record.streamTitle === 'string' &&
    typeof record.gameName === 'string' &&
    typeof record.campaignId === 'string' &&
    typeof record.campaignName === 'string' &&
    typeof record.targetMinutes === 'number' &&
    typeof record.startedAt === 'number' &&
    typeof record.accumulatedMs === 'number' &&
    (record.resumedAt === null || typeof record.resumedAt === 'number')
  )
}

function readSession(): WatchSession | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    const raw = window.localStorage.getItem(WATCH_SESSION_STORAGE_KEY)
    if (!raw) {
      return null
    }

    const parsed: unknown = JSON.parse(raw)
    if (!isWatchSession(parsed)) {
      return null
    }
    if (Date.now() - parsed.startedAt > STALE_AFTER_MS) {
      return null
    }

    return parsed
  } catch {
    return null
  }
}

function storeSession(session: WatchSession | null): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    if (session) {
      window.localStorage.setItem(WATCH_SESSION_STORAGE_KEY, JSON.stringify(session))
    } else {
      window.localStorage.removeItem(WATCH_SESSION_STORAGE_KEY)
    }
  } catch {
    // Storage can be unavailable in private/restricted contexts.
  }
}

export function useWatchSession() {
  const [session, setSession] = useState<WatchSession | null>(readSession)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    storeSession(session)
  }, [session])

  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key === WATCH_SESSION_STORAGE_KEY) {
        setSession(readSession())
      }
    }

    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const isRunning = session !== null && session.resumedAt !== null

  useEffect(() => {
    if (!isRunning) {
      return
    }

    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isRunning])

  const start = useCallback((input: WatchSessionStart) => {
    const startedAt = Date.now()
    setNow(startedAt)
    setSession({
      ...input,
      startedAt,
      accumulatedMs: 0,
      resumedAt: startedAt,
    })
  }, [])

  const pause = useCallback(() => {
    setSession((current) => {
      if (!current || current.resumedAt === null) {
        return current
      }

      const stamp = Date.now()
      return {
        ...current,
        accumulatedMs:
          current.accumulatedMs + Math.max(0, stamp - current.resumedAt),
        resumedAt: null,
      }
    })
  }, [])

  const resume = useCallback(() => {
    const stamp = Date.now()
    setNow(stamp)
    setSession((current) => {
      if (!current || current.resumedAt !== null) {
        return current
      }

      return { ...current, resumedAt: stamp }
    })
  }, [])

  const stop = useCallback(() => {
    setSession(null)
  }, [])

  const elapsedMs = useMemo(() => {
    if (!session) {
      return 0
    }

    const runningMs = session.resumedAt
      ? Math.max(0, now - session.resumedAt)
      : 0
    return session.accumulatedMs + runningMs
  }, [session, now])

  return { session, elapsedMs, isRunning, start, pause, resume, stop }
}

export type WatchSessionState = ReturnType<typeof useWatchSession>
