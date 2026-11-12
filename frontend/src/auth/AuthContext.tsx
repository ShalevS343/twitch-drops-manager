import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError, api, setUnauthorizedHandler } from '../api/client'
import type { AuthMe, AuthUser, Registration, TwitchLoginResult } from '../api/types'

interface AuthContextValue {
  /** Raw `/auth/me` payload, including registration and Telegram settings. */
  me: AuthMe | null
  /** The signed-in local account, or null when the visitor is not authenticated. */
  user: AuthUser | null
  registration: Registration
  telegramBotConfigured: boolean
  isAdmin: boolean
  isLoading: boolean
  error: string | null
  notice: string | null
  login: (redirectUrl: string, inviteCode?: string) => Promise<TwitchLoginResult>
  logout: () => Promise<void>
  refresh: () => Promise<AuthMe | null>
  clearNotice: () => void
}

const ANONYMOUS_REGISTRATION: Registration = { open: false, invite_required: false }

const SESSION_EXPIRED_NOTICE = 'Your session expired. Sign in again.'

const AuthContext = createContext<AuthContextValue | null>(null)

function identityOf(me: AuthMe | null): number | null {
  return me?.authenticated && me.user ? me.user.id : null
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const [me, setMe] = useState<AuthMe | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Last identity whose data may still be in the query cache. Whenever this
  // changes, every cached query is cancelled and dropped so a shared browser can
  // never render the previous user's data.
  const identityRef = useRef<number | null>(null)
  const pendingRef = useRef<Promise<AuthMe | null> | null>(null)

  const purgeCaches = useCallback(async () => {
    await queryClient.cancelQueries()
    queryClient.clear()
  }, [queryClient])

  /**
   * Drops the current identity immediately. Teardown never waits on `/auth/me`,
   * so a failed or slow reload cannot leave the previous user rendered. The
   * registration flags are public data and are kept for the gate.
   */
  const clearIdentity = useCallback(async () => {
    identityRef.current = null
    await purgeCaches()
    setMe((current) => ({
      authenticated: false,
      registration: current?.registration ?? ANONYMOUS_REGISTRATION,
      telegram_bot_configured: current?.telegram_bot_configured ?? false,
    }))
  }, [purgeCaches])

  const load = useCallback(() => {
    if (pendingRef.current) return pendingRef.current

    const pending = (async () => {
      try {
        const next = await api.authMe()
        const nextIdentity = identityOf(next)

        if (identityRef.current !== nextIdentity) {
          await purgeCaches()
          identityRef.current = nextIdentity
        }

        setMe(next)
        setError(null)
        return next
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          // A dead session must not keep the old user on screen even though the
          // reload failed.
          setNotice(SESSION_EXPIRED_NOTICE)
          await clearIdentity()
        } else {
          setError(err instanceof Error ? err.message : 'Could not reach the server')
        }
        return null
      } finally {
        setIsLoading(false)
        pendingRef.current = null
      }
    })()

    pendingRef.current = pending
    return pending
  }, [clearIdentity, purgeCaches])

  const settlePending = useCallback(async () => {
    const pending = pendingRef.current
    if (pending) {
      await pending.catch(() => null)
    }
  }, [])

  /**
   * Lets any in-flight `/auth/me` settle before loading again. Without this, a
   * request that started before a mutation (or login/logout) could resolve with
   * stale identity/profile data and win the race.
   */
  const refresh = useCallback(async () => {
    await settlePending()
    return load()
  }, [load, settlePending])

  /**
   * Ends the local session immediately: identity, caches and rendered user are
   * gone before the best-effort `/auth/me` reload that refreshes public
   * registration flags.
   */
  const endSession = useCallback(
    async (message: string | null) => {
      setNotice(message)
      await settlePending()
      await clearIdentity()
      void load()
    },
    [clearIdentity, load, settlePending],
  )

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      void endSession(SESSION_EXPIRED_NOTICE)
    })

    return () => setUnauthorizedHandler(null)
  }, [endSession])

  // Another tab may sign out or the session may expire while this tab is in the
  // background. Re-check whenever the tab regains focus, becomes visible, or is
  // restored from the back/forward cache. A BFCache restore keeps the frozen
  // React state, so without `pageshow` it could keep showing the previous user.
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        void refresh()
      }
    }
    const handleFocus = () => {
      void refresh()
    }
    const handlePageShow = (event: PageTransitionEvent) => {
      // A normal page load already runs the initial load effect above; only a
      // restored page needs an extra check.
      if (event.persisted) {
        void refresh()
      }
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('focus', handleFocus)
    window.addEventListener('pageshow', handlePageShow)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('focus', handleFocus)
      window.removeEventListener('pageshow', handlePageShow)
    }
  }, [refresh])

  const login = useCallback(
    async (redirectUrl: string, inviteCode?: string) => {
      const result = await api.twitchConnect(redirectUrl, inviteCode)
      setNotice(null)
      await refresh()
      return result
    },
    [refresh],
  )

  const logout = useCallback(async () => {
    // Let the request fail loudly and keep the session intact if the server did
    // not clear it; once it succeeds, tear the local side down immediately.
    await api.logout()
    await endSession(null)
  }, [endSession])

  const user = me?.authenticated ? me.user ?? null : null

  const value = useMemo<AuthContextValue>(
    () => ({
      me,
      user,
      registration: me?.registration ?? ANONYMOUS_REGISTRATION,
      telegramBotConfigured: me?.telegram_bot_configured ?? false,
      isAdmin: user?.role === 'admin',
      isLoading,
      error,
      notice,
      login,
      logout,
      refresh,
      clearNotice: () => setNotice(null),
    }),
    [me, user, isLoading, error, notice, login, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return context
}
