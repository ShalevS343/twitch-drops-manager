import { useCallback, useEffect, useState } from 'react'

import { TAB_IDS, type TabId } from '../lib/tabs'

function readTab(): TabId {
  const raw = window.location.hash
    .replace(/^#\/?/, '')
    .replace(/\/+$/, '')
    .toLowerCase()

  if ((TAB_IDS as readonly string[]).includes(raw)) {
    return raw as TabId
  }

  return 'overview'
}

export function useTab() {
  const [tab, setTab] = useState<TabId>(readTab)

  useEffect(() => {
    const sync = () => setTab(readTab())
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])

  const navigate = useCallback((next: TabId) => {
    const target = `#/${next}`
    if (window.location.hash === target) {
      setTab(next)
      return
    }
    window.location.hash = target
  }, [])

  return { tab, navigate }
}
