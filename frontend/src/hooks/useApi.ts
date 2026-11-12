import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { UpdateMeInput } from '../api/types'
import { useAuth } from '../auth/AuthContext'

/**
 * Personal data is always cached under `['u', user.id, ...]`. The auth provider
 * clears the whole cache when the signed-in identity changes, and the id in the
 * key is a second line of defence so one user's data can never serve another.
 */
function useUserScope(): number | string {
  const { user } = useAuth()
  return user?.id ?? 'anonymous'
}

function useUserKey(scope: string) {
  const id = useUserScope()
  return ['u', id, scope] as const
}

export function useStatus() {
  const key = useUserKey('status')
  return useQuery({
    queryKey: key,
    queryFn: api.status,
    refetchInterval: 30_000,
  })
}

export function useGames() {
  const key = useUserKey('games')
  return useQuery({ queryKey: key, queryFn: api.games })
}

export function useCampaigns() {
  const key = useUserKey('campaigns')
  return useQuery({ queryKey: key, queryFn: api.campaigns })
}

export function useStreams() {
  const key = useUserKey('streams')
  return useQuery({ queryKey: key, queryFn: api.streams })
}

export function useSaveGames() {
  const queryClient = useQueryClient()
  const userId = useUserScope()

  return useMutation({
    mutationFn: api.updateGames,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'games'] })
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'streams'] })
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'watch-queue'] })
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'status'] })
    },
  })
}

export function useScan() {
  const queryClient = useQueryClient()
  const userId = useUserScope()

  return useMutation({
    mutationFn: api.scan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['u', userId] })
    },
  })
}

export function useTestTelegram() {
  return useMutation({ mutationFn: api.testTelegram })
}

export function useCreateTelegramLink() {
  return useMutation({ mutationFn: api.createTelegramLink })
}

export function useUnlinkTelegram() {
  const queryClient = useQueryClient()
  const userId = useUserScope()
  const { refresh } = useAuth()

  return useMutation({
    mutationFn: api.unlinkTelegram,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['u', userId] })
      await refresh()
    },
  })
}

export function useProgress() {
  const key = useUserKey('progress')
  return useQuery({
    queryKey: key,
    queryFn: api.progress,
    refetchInterval: 60_000,
  })
}

export function useWatchQueue() {
  const key = useUserKey('watch-queue')
  return useQuery({
    queryKey: key,
    queryFn: api.watchQueue,
    refetchInterval: 30_000,
  })
}

export function useWatcher() {
  const key = useUserKey('watcher')
  return useQuery({
    queryKey: key,
    queryFn: api.watcher,
    refetchInterval: 15_000,
  })
}

export function useSetWatcherEnabled() {
  const queryClient = useQueryClient()
  const userId = useUserScope()

  return useMutation({
    mutationFn: api.setWatcherEnabled,
    onSuccess: (state) => {
      queryClient.setQueryData(['u', userId, 'watcher'], state)
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'watch-queue'] })
    },
  })
}

export function useFocusWatcher() {
  const queryClient = useQueryClient()
  const userId = useUserScope()

  return useMutation({
    mutationFn: api.focusWatcher,
    onSuccess: (state) => {
      queryClient.setQueryData(['u', userId, 'watcher'], state)
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'watch-queue'] })
    },
  })
}

export function useStopWatcher() {
  const queryClient = useQueryClient()
  const userId = useUserScope()

  return useMutation({
    mutationFn: api.stopWatcher,
    onSuccess: (state) => {
      queryClient.setQueryData(['u', userId, 'watcher'], state)
    },
  })
}

export function useTwitchStatus() {
  const key = useUserKey('twitch-status')
  return useQuery({
    queryKey: key,
    queryFn: api.twitchStatus,
    refetchInterval: 60_000,
  })
}

export function useRefreshProgress() {
  const queryClient = useQueryClient()
  const userId = useUserScope()

  return useMutation({
    mutationFn: api.refreshProgress,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'progress'] })
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'watch-queue'] })
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'twitch-status'] })
      queryClient.invalidateQueries({ queryKey: ['u', userId, 'status'] })
    },
  })
}

export function useTwitchDisconnect() {
  const queryClient = useQueryClient()
  const userId = useUserScope()
  const { refresh } = useAuth()

  return useMutation({
    mutationFn: api.twitchDisconnect,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['u', userId] })
      await refresh()
    },
  })
}

export function useUpdateMe() {
  const queryClient = useQueryClient()
  const userId = useUserScope()
  const { refresh } = useAuth()

  return useMutation({
    mutationFn: (input: UpdateMeInput) => api.updateMe(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['u', userId] })
      await refresh()
    },
  })
}

export function useAdminUsers() {
  const { isAdmin } = useAuth()
  const key = useUserKey('admin-users')

  return useQuery({
    queryKey: key,
    queryFn: api.adminUsers,
    enabled: isAdmin,
  })
}

export function useUpdateAdminUser() {
  const queryClient = useQueryClient()
  const { isAdmin } = useAuth()
  const userId = useUserScope()

  return useMutation({
    mutationFn: ({ id, isActive }: { id: number; isActive: boolean }) =>
      api.setUserActive(id, isActive),
    onSuccess: () => {
      if (isAdmin) {
        queryClient.invalidateQueries({ queryKey: ['u', userId, 'admin-users'] })
      }
    },
  })
}

export type StatusQuery = ReturnType<typeof useStatus>
export type TwitchStatusQuery = ReturnType<typeof useTwitchStatus>
