import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'

export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: api.status,
    refetchInterval: 30_000,
  })
}

export function useGames() {
  return useQuery({ queryKey: ['games'], queryFn: api.games })
}

export function useCampaigns() {
  return useQuery({ queryKey: ['campaigns'], queryFn: api.campaigns })
}

export function useStreams() {
  return useQuery({ queryKey: ['streams'], queryFn: api.streams })
}

export function useSaveGames() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.updateGames,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['games'] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })
}

export function useScan() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.scan,
    onSuccess: () => {
      queryClient.invalidateQueries()
    },
  })
}

export function useTestTelegram() {
  return useMutation({ mutationFn: api.testTelegram })
}

export function useProgress() {
  return useQuery({
    queryKey: ['progress'],
    queryFn: api.progress,
    refetchInterval: 60_000,
  })
}

export function useWatchQueue() {
  return useQuery({
    queryKey: ['watch-queue'],
    queryFn: api.watchQueue,
    refetchInterval: 30_000,
  })
}

export function useWatcher() {
  return useQuery({
    queryKey: ['watcher'],
    queryFn: api.watcher,
    refetchInterval: 15_000,
  })
}

export function useSetWatcherEnabled() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.setWatcherEnabled,
    onSuccess: (state) => {
      queryClient.setQueryData(['watcher'], state)
      queryClient.invalidateQueries({ queryKey: ['watch-queue'] })
    },
  })
}

export function useFocusWatcher() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.focusWatcher,
    onSuccess: (state) => {
      queryClient.setQueryData(['watcher'], state)
      queryClient.invalidateQueries({ queryKey: ['watch-queue'] })
    },
  })
}

export function useStopWatcher() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.stopWatcher,
    onSuccess: (state) => {
      queryClient.setQueryData(['watcher'], state)
    },
  })
}

export function useTwitchStatus() {
  return useQuery({
    queryKey: ['twitch-status'],
    queryFn: api.twitchStatus,
    refetchInterval: 60_000,
  })
}

export function useRefreshProgress() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.refreshProgress,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['progress'] })
      queryClient.invalidateQueries({ queryKey: ['watch-queue'] })
      queryClient.invalidateQueries({ queryKey: ['twitch-status'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })
}

export function useTwitchLogout() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.twitchLogout,
    onSuccess: () => {
      queryClient.invalidateQueries()
    },
  })
}

export type StatusQuery = ReturnType<typeof useStatus>
export type TwitchStatusQuery = ReturnType<typeof useTwitchStatus>
