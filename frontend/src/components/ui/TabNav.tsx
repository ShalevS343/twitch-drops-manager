import type { KeyboardEvent } from 'react'

import type { TabId, TabMeta } from '../../lib/tabs'
import { Icon } from './Icon'

interface TabNavProps {
  tabs: TabMeta[]
  active: TabId
  onNavigate: (tab: TabId) => void
}

export function TabNav({ tabs, active, onNavigate }: TabNavProps) {
  function handleKeyDown(event: KeyboardEvent<HTMLAnchorElement>, index: number) {
    if (
      event.key !== 'ArrowDown' &&
      event.key !== 'ArrowUp' &&
      event.key !== 'ArrowLeft' &&
      event.key !== 'ArrowRight' &&
      event.key !== 'Home' &&
      event.key !== 'End'
    ) {
      return
    }

    event.preventDefault()
    let nextIndex = index

    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
      nextIndex = (index + 1) % tabs.length
    }
    if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
      nextIndex = (index - 1 + tabs.length) % tabs.length
    }
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = tabs.length - 1

    const next = tabs[nextIndex]
    onNavigate(next.id)
    const target = document.getElementById(`nav-${next.id}`)
    target?.focus()
  }

  return (
    <nav className="sidebar-nav" aria-label="Dashboard sections">
      {tabs.map((tab, index) => {
        const isActive = tab.id === active
        return (
          <a
            key={tab.id}
            id={`nav-${tab.id}`}
            href={`#/${tab.id}`}
            className={`nav-link${isActive ? ' active' : ''}`}
            aria-current={isActive ? 'page' : undefined}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            <Icon name={tab.icon} size={18} />
            <span>{tab.label}</span>
          </a>
        )
      })}
    </nav>
  )
}
