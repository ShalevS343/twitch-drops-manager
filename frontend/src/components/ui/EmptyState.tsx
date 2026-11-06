import type { ReactNode } from 'react'

import { Icon, type IconName } from './Icon'

interface EmptyStateProps {
  icon?: IconName
  title: string
  message?: string
  action?: ReactNode
  compact?: boolean
}

export function EmptyState({
  icon = 'inbox',
  title,
  message,
  action,
  compact = false,
}: EmptyStateProps) {
  return (
    <div className={`empty-state${compact ? ' empty-state-compact' : ''}`}>
      <span className="empty-icon" aria-hidden="true">
        <Icon name={icon} size={compact ? 20 : 24} />
      </span>
      <h3>{title}</h3>
      {message && <p>{message}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  )
}
