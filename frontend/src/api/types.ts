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
  completed: boolean
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
  user: AuthUser | null
  twitch_configured: boolean
  telegram_configured: boolean
  telegram_ready: boolean
  games_selected: string[]
  campaign_count: number
  stream_count: number
  last_scan: ScanRun | null
  last_error: string | null
  twitch_user_connected: boolean
  twitch_login: string | null
  poll_seconds: number
  min_poll_seconds: number
  progress_poll_seconds: number
  min_progress_poll_seconds: number
  watcher_poll_seconds: number
  min_watcher_poll_seconds: number
  drops_api_keyed: boolean
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
}

export interface WatchQueueCampaign {
  campaign_id: string
  campaign_name: string
  ends_at: string | null
  remaining_minutes: number
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

export type WatchStatus = 'idle' | 'focused' | 'offline' | 'waiting'

export interface WatchCandidate {
  stream_id: number
  user_login: string
  user_name: string
  stream_url: string
  stream_title: string
  game_name: string
  game_box_art_url: string
  viewers: number
  campaign_id: string
  campaign_name: string
  target_minutes: number
  ends_at: string | null
}

export interface WatchFocus {
  stream_id: number | null
  user_login: string
  user_name: string
  stream_url: string
  stream_title: string
  game_name: string
  game_box_art_url: string
  campaign_id: string
  campaign_name: string
  target_minutes: number
  ends_at: string | null
  reason: string
  focused_at: string | null
  updated_at: string | null
}

export interface WatchState {
  enabled: boolean
  status: WatchStatus
  reason: string
  max_watchers: number
  auto_move: boolean
  focus: WatchFocus | null
  candidates: WatchCandidate[]
  updated_at: string | null
}

export interface WatchFocusInput {
  stream_id?: number
  campaign_id?: string
  strategy: 'manual' | 'auto' | 'next'
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
  display_name: string | null
  profile_image_url: string | null
  connected_at: string | null
  reconnect_required?: boolean
  last_error?: string | null
  last_synced_at?: string | null
}

export interface TwitchConnect {
  authorize_url: string
  redirect_uri: string
}

export type UserRole = 'admin' | 'user'

export interface AuthUser {
  id: number
  login: string
  display_name: string
  profile_image_url: string | null
  role: UserRole
  telegram_enabled: boolean
  telegram_chat_id: string | null
}

export interface TelegramLink {
  deep_link: string
  expires_at: string
}

export interface Registration {
  open: boolean
  invite_required: boolean
}

export interface AuthMe {
  authenticated: boolean
  user?: AuthUser | null
  registration: Registration
  telegram_bot_configured: boolean
}

export interface TwitchLoginResult {
  connected: boolean
  user: AuthUser
  created: boolean
}

export interface UpdateMeInput {
  telegram_chat_id?: string
  telegram_enabled?: boolean
}

export interface AdminUser {
  id: number
  login: string
  display_name: string
  profile_image_url?: string | null
  role: UserRole
  /** The API may expose either name for the account flag. */
  is_active?: boolean
  active?: boolean
  created_at?: string | null
  last_login_at?: string | null
  telegram_enabled?: boolean
}
