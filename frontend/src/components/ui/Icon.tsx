import type { ReactNode } from 'react'

export type IconName =
  | 'home'
  | 'gift'
  | 'chart'
  | 'play'
  | 'radio'
  | 'settings'
  | 'user'
  | 'scan'
  | 'refresh'
  | 'search'
  | 'menu'
  | 'external'
  | 'link'
  | 'check'
  | 'alert'
  | 'clock'
  | 'inbox'
  | 'twitch'
  | 'logout'
  | 'copy'
  | 'sparkles'
  | 'x'
  | 'plus'
  | 'arrow-right'
  | 'target'

/**
 * Custom solid/geometric icon set. Primary navigation icons are filled
 * silhouettes; utility icons use square-capped strokes. Deliberately not a
 * generic rounded outline set.
 */
const ICONS: Record<IconName, ReactNode> = {
  home: <path d="M12 2 2 10.2V22h8v-6h4v6h8V10.2L12 2Z" />,
  gift: (
    <>
      <path
        fillRule="evenodd"
        d="M2 8h20v5H2V8Zm2 5h16v10H4V13Zm6.75-5h2.5v15h-2.5V8Z"
      />
      <circle cx="8.6" cy="5.9" r="2.1" />
      <circle cx="15.4" cy="5.9" r="2.1" />
    </>
  ),
  chart: (
    <>
      <rect x="2" y="21" width="20" height="1.6" />
      <rect x="3" y="12" width="4" height="7" />
      <rect x="10" y="6" width="4" height="13" />
      <rect x="17" y="9" width="4" height="10" />
    </>
  ),
  play: <path d="M7 4 21 12 7 20Z" />,
  radio: (
    <>
      <circle cx="12" cy="12" r="2.6" />
      <g fill="none" stroke="currentColor">
        <path d="M7.4 7.4a6.5 6.5 0 0 0 0 9.2" />
        <path d="M16.6 7.4a6.5 6.5 0 0 1 0 9.2" />
        <path d="M4.3 4.3a10.9 10.9 0 0 0 0 15.4" />
        <path d="M19.7 4.3a10.9 10.9 0 0 1 0 15.4" />
      </g>
    </>
  ),
  settings: (
    <>
      <rect x="2" y="5" width="20" height="1.8" />
      <rect x="14" y="2.9" width="4" height="6" />
      <rect x="2" y="11.1" width="20" height="1.8" />
      <rect x="6" y="9" width="4" height="6" />
      <rect x="2" y="17.2" width="20" height="1.8" />
      <rect x="15" y="15.1" width="4" height="6" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="7.4" r="4" />
      <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7H4Z" />
    </>
  ),
  scan: (
    <>
      <path
        fillRule="evenodd"
        d="M10.5 2.6a7.6 7.6 0 1 0 0 15.2 7.6 7.6 0 0 0 0-15.2Zm0 2.3a5.3 5.3 0 1 1 0 10.6 5.3 5.3 0 0 1 0-10.6Z"
      />
      <path d="M16.1 14.6 22 20.5l-1.5 1.5-5.9-5.9 1.5-1.5Z" />
    </>
  ),
  refresh: (
    <g fill="none" stroke="currentColor">
      <path d="M20 12a8 8 0 1 1-2.4-5.7" />
      <path d="M20 3.2V9h-5.8" />
    </g>
  ),
  search: (
    <>
      <path
        fillRule="evenodd"
        d="M10.5 2.6a7.6 7.6 0 1 0 0 15.2 7.6 7.6 0 0 0 0-15.2Zm0 2.3a5.3 5.3 0 1 1 0 10.6 5.3 5.3 0 0 1 0-10.6Z"
      />
      <path d="M16.1 14.6 22 20.5l-1.5 1.5-5.9-5.9 1.5-1.5Z" />
    </>
  ),
  menu: (
    <>
      <rect x="2" y="5" width="20" height="2" />
      <rect x="2" y="11" width="20" height="2" />
      <rect x="2" y="17" width="20" height="2" />
    </>
  ),
  external: (
    <g fill="none" stroke="currentColor">
      <path d="M14 3h7v7" />
      <path d="M21 3l-9.5 9.5" />
      <path d="M10 5H4.8A1.8 1.8 0 0 0 3 6.8v12.4A1.8 1.8 0 0 0 4.8 21h12.4a1.8 1.8 0 0 0 1.8-1.8V14" />
    </g>
  ),
  link: (
    <g fill="none" stroke="currentColor">
      <path d="M10 14a4.2 4.2 0 0 0 6 0l2.4-2.4a4.2 4.2 0 0 0-6-6L11.2 6.8" />
      <path d="M14 10a4.2 4.2 0 0 0-6 0l-2.4 2.4a4.2 4.2 0 0 0 6 6l1.2-1.2" />
    </g>
  ),
  check: (
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      d="M20 6 9 17l-5-5"
    />
  ),
  alert: (
    <path
      fillRule="evenodd"
      d="M12 2 23 21H1L12 2Zm-1 7v6.5h2V9h-2Zm0 8.5V20h2v-2.5h-2Z"
    />
  ),
  clock: (
    <>
      <path
        fillRule="evenodd"
        d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 2.2a7.8 7.8 0 1 1 0 15.6 7.8 7.8 0 0 1 0-15.6Z"
      />
      <path d="M11 5.8h2v6.6l4.4 2.6-1 1.7-5.4-3.2V5.8Z" />
    </>
  ),
  inbox: (
    <g fill="none" stroke="currentColor">
      <path d="M3.5 4.5h17v15h-17z" />
      <path d="M3.5 13.5h5l1.8 2.7h3.4l1.8-2.7h5" />
    </g>
  ),
  twitch: (
    <path
      fillRule="evenodd"
      d="M3 4h18v13h-7l-4 4v-4H3V4Zm4 3.8v3.4h2V7.8H7Zm8 0v3.4h2V7.8h-2Z"
    />
  ),
  logout: (
    <g fill="none" stroke="currentColor">
      <path d="M10 3H4.8A1.8 1.8 0 0 0 3 4.8v14.4A1.8 1.8 0 0 0 4.8 21H10" />
      <path d="M15 7l5 5-5 5" />
      <path d="M20 12H9" />
    </g>
  ),
  copy: (
    <g fill="none" stroke="currentColor">
      <rect x="8" y="8" width="12" height="13" />
      <path d="M16 8V3H4v13h4" />
    </g>
  ),
  sparkles: (
    <>
      <path d="M12 2l2.2 6.8L21 11l-6.8 2.2L12 20l-2.2-6.8L3 11l6.8-2.2L12 2Z" />
      <path d="M19 14.8l1 2.6 2.6 1-2.6 1-1 2.6-1-2.6-2.6-1 2.6-1 1-2.6Z" />
    </>
  ),
  x: (
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      d="M18 6 6 18M6 6l12 12"
    />
  ),
  plus: (
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      d="M12 4v16M4 12h16"
    />
  ),
  'arrow-right': (
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      d="M4 11h14M12 4l7 7-7 7"
    />
  ),
  target: (
    <>
      <path
        fillRule="evenodd"
        d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 2.4a7.6 7.6 0 1 1 0 15.2 7.6 7.6 0 0 1 0-15.2Z"
      />
      <path
        fillRule="evenodd"
        d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Zm0 2.4a2.6 2.6 0 1 1 0 5.2 2.6 2.6 0 0 1 0-5.2Z"
      />
      <circle cx="12" cy="12" r="1.4" />
    </>
  ),
}

interface IconProps {
  name: IconName
  size?: number
  className?: string
  strokeWidth?: number
}

export function Icon({ name, size = 18, className, strokeWidth = 2 }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      stroke="none"
      strokeWidth={strokeWidth}
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
      focusable="false"
    >
      {ICONS[name]}
    </svg>
  )
}
