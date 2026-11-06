import type { WatchQueueCampaign, WatchQueueItem } from '../api/types'

export interface WatchSuggestion {
  campaign: WatchQueueCampaign
  stream: WatchQueueItem
}

function campaignEnd(campaign: WatchQueueCampaign): number {
  if (!campaign.ends_at) {
    return Number.POSITIVE_INFINITY
  }

  const parsed = new Date(campaign.ends_at).getTime()
  return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed
}

/**
 * Group the stream-centric queue into one suggestion per campaign, using the
 * most-watched live stream for that campaign. Ordered by the campaign that ends
 * first, then by the largest remaining watch requirement.
 */
export function suggestNextCampaigns(
  items: WatchQueueItem[],
  currentCampaignId: string | null,
  limit = 3,
): WatchSuggestion[] {
  const byCampaign = new Map<string, WatchSuggestion>()

  for (const stream of items) {
    for (const campaign of stream.campaigns) {
      if (campaign.campaign_id === currentCampaignId) {
        continue
      }
      if (campaign.remaining_minutes <= 0) {
        continue
      }

      const existing = byCampaign.get(campaign.campaign_id)
      if (!existing || stream.viewers > existing.stream.viewers) {
        byCampaign.set(campaign.campaign_id, { campaign, stream })
      }
    }
  }

  return [...byCampaign.values()]
    .sort((a, b) => {
      const endDelta = campaignEnd(a.campaign) - campaignEnd(b.campaign)
      if (endDelta !== 0) {
        return endDelta
      }

      return b.campaign.remaining_minutes - a.campaign.remaining_minutes
    })
    .slice(0, limit)
}
