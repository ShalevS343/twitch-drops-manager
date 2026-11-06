interface SpinnerProps {
  size?: number
  className?: string
}

export function Spinner({ size = 18, className = '' }: SpinnerProps) {
  return (
    <span
      className={`spinner ${className}`.trim()}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  )
}

interface LoadingStateProps {
  label?: string
}

export function LoadingState({ label = 'Loading…' }: LoadingStateProps) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <Spinner />
      <span>{label}</span>
    </div>
  )
}
