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
