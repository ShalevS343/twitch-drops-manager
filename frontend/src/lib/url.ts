const SAFE_PROTOCOLS = new Set(['http:', 'https:'])

/**
 * Returns a normalized absolute URL that is safe to render in `href`/`src`,
 * or `null` when the value is missing, malformed, or uses another protocol.
 *
 * API-controlled links (`details_url`, stream URLs, OAuth/deep links, avatars)
 * must pass through this helper before they reach the DOM. In particular,
 * `javascript:`, `data:`, and `vbscript:` URLs are rejected so a compromised or
 * malicious API payload cannot execute script or navigate to a non-web scheme.
 * Protocol-relative and backslash variants are rejected before normalization
 * because browsers resolve them away from the current origin.
 */
export function safeExternalUrl(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null

  const trimmed = value.trim()
  if (!trimmed) return null

  if (/^[\\/]{2}/.test(trimmed)) return null

  try {
    const base =
      typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
    const parsed = new URL(trimmed, base)
    return SAFE_PROTOCOLS.has(parsed.protocol) ? parsed.href : null
  } catch {
    return null
  }
}
