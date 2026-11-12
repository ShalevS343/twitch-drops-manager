import type { ReactNode } from 'react'

import { useAuth } from '../auth/AuthContext'
import { AuthPage } from '../pages/AuthPage'
import { Icon } from './ui/Icon'
import { Spinner } from './ui/Spinner'

function AuthSplash() {
  return (
    <div className="auth-shell">
      <div className="auth-card auth-splash" role="status" aria-live="polite">
        <span className="brand-mark">
          <Icon name="gift" size={20} />
        </span>
        <Spinner size={22} />
        <span>Checking your session…</span>
      </div>
    </div>
  )
}

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()

  if (isLoading) return <AuthSplash />
  if (!user) return <AuthPage />
  return <>{children}</>
}
