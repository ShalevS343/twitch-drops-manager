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
}

export interface ScanResult {
  ok: boolean
  campaign_count: number
  stream_count: number
  notified_count: number
}
