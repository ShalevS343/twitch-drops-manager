import { useEffect, useState } from 'react'

interface AvatarProps {
  name?: string | null
  src?: string | null
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase()
}

export function Avatar({ name, src, size = 'md', className = '' }: AvatarProps) {
  const label = name || 'Twitch user'
  const [imageFailed, setImageFailed] = useState(false)

  useEffect(() => {
    setImageFailed(false)
  }, [src])

  const showImage = Boolean(src) && !imageFailed

  return (
    <span className={`avatar avatar-${size} ${className}`.trim()} title={label}>
      {showImage ? (
        // Twitch avatar URLs are remote assets. An empty alt keeps the name as
        // the accessible label via the wrapper title.
        <img
          src={src ?? undefined}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <span aria-hidden="true">{initials(label)}</span>
      )}
    </span>
  )
}
