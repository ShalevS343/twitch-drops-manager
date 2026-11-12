import type { IconName } from '../components/ui/Icon'

export const TAB_IDS = [
  'overview',
  'campaigns',
  'progress',
  'watch-queue',
  'streams',
  'settings',
  'profile',
] as const

export type TabId = (typeof TAB_IDS)[number]

export interface TabMeta {
  id: TabId
  label: string
  title: string
  subtitle: string
  icon: IconName
}

export const TABS: TabMeta[] = [
  {
    id: 'overview',
    label: 'Overview',
    title: 'Overview',
    subtitle: 'Your drops, live streams, and what needs attention.',
    icon: 'home',
  },
  {
    id: 'campaigns',
    label: 'Campaigns',
    title: 'Campaigns',
    subtitle: 'Browse every tracked campaign and its rewards.',
    icon: 'gift',
  },
  {
    id: 'progress',
    label: 'Progress',
    title: 'Drop progress',
    subtitle: 'Track drop completion, remaining time, and current pace.',
    icon: 'chart',
  },
  {
    id: 'watch-queue',
    label: 'Watch queue',
    title: 'Watch queue',
    subtitle: 'Eligible live streams ordered by the drops they advance.',
    icon: 'play',
  },
  {
    id: 'streams',
    label: 'Streams',
    title: 'Live streams',
    subtitle: 'Live Drops-enabled streams for your selected games.',
    icon: 'radio',
  },
  {
    id: 'settings',
    label: 'Settings',
    title: 'Settings',
    subtitle: 'Games, Telegram, Twitch connection, and system status.',
    icon: 'settings',
  },
  {
    id: 'profile',
    label: 'Profile',
    title: 'Profile',
    subtitle: 'Your account, Twitch connection, and Telegram settings.',
    icon: 'user',
  },
]
