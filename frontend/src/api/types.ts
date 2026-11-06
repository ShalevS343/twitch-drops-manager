export interface Game {
  id: number
  name: string
  box_art_url: string
  twitch_game_id: string | null
  selected: boolean
  campaign_count: number
}

export interface Reward {
  id: number
  name: string
  benefit_name: string
  required_minutes: number
}

export interface Campaign {
  id: number
  external_id: string
  name: string
  status: string
  starts_at: string | null
  ends_at: string | null
  details_url: string
  owner_name: string
  game: Game
  rewards: Reward[]
}

export interface Stream {
  id: number
  user_login: string
  user_name: string
  title: string
  viewers: number
  language: string
  started_at: string | null
  url: string
  live: boolean
  game: Game
  matching_campaigns: string[]
}

export interface ScanRun {
  id: number
  started_at: string
  finished_at: string | null
  ok: boolean
  error: string | null
  campaign_count: number
  stream_count: number
}

export interface Status {
  app: string
  twitch_configured: boolean
  telegram_configured: boolean
  games_selected: string[]
  campaign_count: number
  stream_count: number
  last_scan: ScanRun | null
  last_error: string | null
  twitch_user_connected: boolean
  twitch_login: string | null
}

export interface ScanResult {
  ok: boolean
  campaign_count: number
  stream_count: number
  notified_count: number
}

export interface ProgressDrop {
  drop_id: string
  drop_name: string
  required_minutes: number
  current_minutes: number
  percent: number
  is_claimed: boolean
  is_ready: boolean
  starts_at: string | null
  ends_at: string | null
  benefits: string[]
  remaining_minutes: number
  rate_minutes_per_hour: number | null
  eta_minutes: number | null
}

export interface ProgressCampaign {
  campaign_id: string
  campaign_name: string
  game_name: string
  game_box_art_url: string
  campaign_ends_at: string | null
  claimed_count: number
  total_count: number
  drops: ProgressDrop[]
  remaining_minutes: number
  eta_minutes: number | null
}

export interface WatchQueueCampaign {
  campaign_id: string
  campaign_name: string
  ends_at: string | null
  remaining_minutes: number
  eta_minutes: number | null
  next_drop_name: string | null
  next_drop_remaining_minutes: number | null
}

export interface WatchQueueItem {
  stream_id: number
  user_login: string
  user_name: string
  title: string
  viewers: number
  language: string
  url: string
  game_name: string
  game_box_art_url: string
  campaigns: WatchQueueCampaign[]
}

export interface ProgressRefresh {
  connected: boolean
  campaign_count: number
  drop_count: number
  notified_count: number
}

export interface TwitchUserStatus {
  connected: boolean
  login: string | null
  user_id: string | null
  expires_at: string | null
}

export interface TwitchConnect {
  authorize_url: string
  redirect_uri: string
}

export interface TwitchConnectResult {
  connected: boolean
  login: string | null
  message: string | null
}
