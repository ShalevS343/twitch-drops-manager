import type { ReactNode } from 'react'

export type BadgeTone =
  | 'neutral'
  | 'accent'
  | 'success'
  | 'warning'
  | 'danger'
  | 'live'
  | 'muted'

interface BadgeProps {
  children: ReactNode
  tone?: BadgeTone
  dot?: boolean
  className?: string
  title?: string
}

export function Badge({
  children,
  tone = 'neutral',
  dot = false,
  className = '',
  title,
}: BadgeProps) {
  return (
    <span className={`badge badge-${tone} ${className}`.trim()} title={title}>
      {dot && <span className="badge-dot" aria-hidden="true" />}
      {children}
    </span>
  )
}
