import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { api, setUnauthorizedHandler } from '../api/client'
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
        setError(err instanceof Error ? err.message : 'Could not reach the server')
        return null
      } finally {
        setIsLoading(false)
        pendingRef.current = null
      }
    })()

    pendingRef.current = pending
    return pending
  }, [purgeCaches])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setNotice('Your session expired. Sign in again.')
      void load()
    })

    return () => setUnauthorizedHandler(null)
  }, [load])

  const refresh = useCallback(() => load(), [load])

  /**
   * Lets any in-flight `/auth/me` settle before reloading. Without this, a
   * request started just before login/logout could resolve with the previous
   * identity and win the race.
   */
  const reload = useCallback(async () => {
    const pending = pendingRef.current
    if (pending) {
      await pending.catch(() => null)
    }
    return load()
  }, [load])

  const login = useCallback(
    async (redirectUrl: string, inviteCode?: string) => {
      const result = await api.twitchConnect(redirectUrl, inviteCode)
      setNotice(null)
      await reload()
      return result
    },
    [reload],
  )

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      // Reloading /auth/me drops the identity and purges all personal caches.
      setNotice(null)
      await reload()
    }
  }, [reload])

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
