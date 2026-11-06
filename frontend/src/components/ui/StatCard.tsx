import type { ReactNode } from 'react'

import { Icon, type IconName } from './Icon'

type StatTone = 'accent' | 'success' | 'warning' | 'danger'

interface StatCardProps {
  label: string
  value: ReactNode
  hint?: string
  icon: IconName
  tone?: StatTone
}

export function StatCard({ label, value, hint, icon, tone = 'accent' }: StatCardProps) {
  return (
    <article className={`stat-card stat-${tone}`}>
      <div className="stat-card-top">
        <span className="stat-icon">
          <Icon name={icon} size={20} />
        </span>
        <span className="stat-label">{label}</span>
      </div>
      <strong className="stat-value">{value}</strong>
      {hint && <span className="stat-hint">{hint}</span>}
    </article>
  )
}
