import type { Campaign, ProgressCampaign } from '../api/types'

export type CampaignPhase = 'active' | 'upcoming' | 'ended' | 'unknown'

export function campaignPhase(campaign: Campaign): CampaignPhase {
  const status = campaign.status?.toUpperCase() ?? ''

  if (status === 'ACTIVE') return 'active'
  if (status === 'UPCOMING' || status === 'SCHEDULED') return 'upcoming'
  if (status === 'ENDED' || status === 'EXPIRED' || status === 'COMPLETED') {
    return 'ended'
  }

  const now = Date.now()
  if (campaign.ends_at && new Date(campaign.ends_at).getTime() < now) return 'ended'
  if (campaign.starts_at && new Date(campaign.starts_at).getTime() > now) {
    return 'upcoming'
  }

  return 'active'
}

export function progressPercent(campaign: ProgressCampaign): number {
  if (campaign.drops.length === 0) return 0

  const total = campaign.drops.reduce((sum, drop) => sum + drop.percent, 0)
  return Math.round(total / campaign.drops.length)
}

export function readyDropCount(campaign: ProgressCampaign): number {
  return campaign.drops.filter((drop) => drop.is_ready && !drop.is_claimed).length
}

export function inProgressDropCount(campaign: ProgressCampaign): number {
  return campaign.drops.filter((drop) => !drop.is_claimed).length
}
