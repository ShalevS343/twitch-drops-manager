import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../api/client'
import type { TwitchDeviceStart, TwitchLoginResult } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { formatDateTime } from '../lib/format'
import { safeExternalUrl } from '../lib/url'
import { Icon } from './ui/Icon'

export type DeviceConnectMode = 'login' | 'reconnect'

export interface DeviceConnectOptions {
  /** Sign-in gate copy and behaviour; defaults to reconnecting an existing user. */
  mode?: DeviceConnectMode
  /** Ask for the shared invite code before starting (unauthenticated gate). */
  inviteRequired?: boolean
  /** Runs after a successful connection. `/auth/me` is always refreshed. */
  onConnected?: () => void | Promise<unknown>
}

export type DevicePhase = 'idle' | 'starting' | 'waiting' | 'success' | 'error'

interface DeviceFlow {
  flowId: string
  userCode: string
  verificationUri: string
  interval: number
  expiresAt: string | null
}

export interface DeviceConnectController {
  flow: DeviceFlow | null
  phase: DevicePhase
  inviteCode: string
  inviteRequired: boolean
  mode: DeviceConnectMode
  starting: boolean
  canceling: boolean
  copied: boolean
  copyFailed: boolean
  error: string | null
  notice: string | null
  retryNotice: string | null
  start: () => Promise<void>
  cancel: () => Promise<void>
  copyCode: () => Promise<void>
  setInviteCode: (value: string) => void
}

const STORAGE_KEY = 'tdm.twitch.device.flow'
const DEFAULT_INTERVAL_SECONDS = 5
const MAX_INTERVAL_SECONDS = 60 * 60
const COPY_FEEDBACK_MS = 2500
const MAX_TRANSIENT_POLL_RETRIES = 3
const TRANSIENT_POLL_STATUSES = new Set([502, 503, 504])
const TRANSIENT_RETRY_MESSAGE =
  'Twitch is temporarily unavailable. Retrying automatically…'

const EXPIRED_MESSAGE =
  'This Twitch code expired. Start a new code to connect.'
const RESUME_EXPIRED_MESSAGE =
  'Your previous Twitch code expired before it was approved. Start a new code to connect.'

interface StoredDeviceFlow {
  flow_id: string
  user_code: string
  interval: number
  verification_uri: string
  expires_at?: string
  mode?: DeviceConnectMode
}

function normalizeInterval(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return null
  return Math.min(Math.max(Math.floor(parsed), 1), MAX_INTERVAL_SECONDS)
}

function isExpired(flow: Pick<DeviceFlow, 'expiresAt'>): boolean {
  if (!flow.expiresAt) return false
  const expiresAt = new Date(flow.expiresAt).getTime()
  return Number.isFinite(expiresAt) && expiresAt <= Date.now()
}

function clearStoredFlow() {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Session storage can be unavailable in private/sandboxed contexts.
  }
}

function persistFlow(flow: DeviceFlow, mode: DeviceConnectMode) {
  const stored: StoredDeviceFlow = {
    flow_id: flow.flowId,
    user_code: flow.userCode,
    interval: flow.interval,
    verification_uri: flow.verificationUri,
    ...(flow.expiresAt ? { expires_at: flow.expiresAt } : {}),
    mode,
  }
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(stored))
  } catch {
    // The flow still works for this page; it just cannot survive a reload.
  }
}

function readStoredFlow(): { flow: DeviceFlow; mode: DeviceConnectMode } | null {
  let raw: string | null = null
  try {
    raw = window.sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
  if (!raw) return null

  try {
    const data = JSON.parse(raw) as Partial<StoredDeviceFlow> | null
    if (
      !data ||
      typeof data.flow_id !== 'string' ||
      !data.flow_id ||
      typeof data.user_code !== 'string' ||
      !data.user_code ||
      typeof data.verification_uri !== 'string' ||
      !data.verification_uri
    ) {
      clearStoredFlow()
      return null
    }

    return {
      flow: {
        flowId: data.flow_id,
        userCode: data.user_code,
        verificationUri: data.verification_uri,
        interval: normalizeInterval(data.interval) ?? DEFAULT_INTERVAL_SECONDS,
        expiresAt:
          typeof data.expires_at === 'string' && data.expires_at
            ? data.expires_at
            : null,
      },
      mode: data.mode === 'reconnect' ? 'reconnect' : 'login',
    }
  } catch {
    clearStoredFlow()
    return null
  }
}

function isPending(
  result: Awaited<ReturnType<typeof api.pollTwitchDevice>>,
): result is { status: 'pending'; interval: number } {
  return (
    typeof result === 'object' &&
    result !== null &&
    'status' in result &&
    result.status === 'pending'
  )
}

function startErrorMessage(err: unknown): string {
  const detail =
    err instanceof Error && err.message.trim()
      ? err.message
      : 'Could not start Twitch code login'
  if (err instanceof ApiError && err.status === 429) {
    return `${detail}. Wait a moment, then try again.`
  }
  return detail
}

function isTransientPollError(err: unknown): boolean {
  return err instanceof ApiError && TRANSIENT_POLL_STATUSES.has(err.status)
}

function pollErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) {
    return 'Could not reach the server while waiting for Twitch. Start a new code to try again. If you already approved this code, the confirmation may not have reached this browser.'
  }
  if (err.status === 409) {
    return `${err.message} Sign out before connecting a different Twitch account.`
  }
  if (err.status === 429) {
    return `${err.message} Wait a moment, then start a new code.`
  }
  if (err.status === 400) {
    return `${err.message} Start a new code to try again. If you already approved this code on Twitch, the confirmation may not have reached this browser.`
  }
  return `${err.message} Start a new code to try again.`
}

/** Clipboard write with a selection fallback for non-secure/older browsers. */
async function copyText(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch {
    // Fall through to the legacy path.
  }

  try {
    const textarea = document.createElement('textarea')
    textarea.value = value
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.top = '0'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    textarea.setSelectionRange(0, value.length)
    const copied = document.execCommand('copy')
    textarea.remove()
    return copied
  } catch {
    return false
  }
}

function toDeviceFlow(info: TwitchDeviceStart): DeviceFlow {
  return {
    flowId: info.flow_id,
    userCode: info.user_code,
    verificationUri: info.verification_uri,
    interval: normalizeInterval(info.interval) ?? DEFAULT_INTERVAL_SECONDS,
    expiresAt: info.expires_at || null,
  }
}

export function useDeviceConnect(
  options: DeviceConnectOptions = {},
): DeviceConnectController {
  const queryClient = useQueryClient()
  const { user, refresh } = useAuth()
  const mode = options.mode ?? 'reconnect'
  const inviteRequired = options.inviteRequired ?? false

  const [flow, setFlow] = useState<DeviceFlow | null>(null)
  const [phase, setPhase] = useState<DevicePhase>('idle')
  const [inviteCode, setInviteCode] = useState('')
  const [starting, setStarting] = useState(false)
  const [canceling, setCanceling] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [retryNotice, setRetryNotice] = useState<string | null>(null)

  const flowRef = useRef<DeviceFlow | null>(null)
  const intervalRef = useRef(DEFAULT_INTERVAL_SECONDS)
  const startingRef = useRef(false)
  const resumedRef = useRef(false)
  const copyTimerRef = useRef<number | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options

  const setActiveFlow = useCallback((next: DeviceFlow | null) => {
    flowRef.current = next
    setFlow(next)
  }, [])

  const finishWithError = useCallback(
    (message: string) => {
      clearStoredFlow()
      setActiveFlow(null)
      intervalRef.current = DEFAULT_INTERVAL_SECONDS
      setCopied(false)
      setCopyFailed(false)
      setRetryNotice(null)
      setPhase('error')
      setError(message)
    },
    [setActiveFlow],
  )

  const finishWithSuccess = useCallback(
    async (result: TwitchLoginResult) => {
      clearStoredFlow()
      setActiveFlow(null)
      intervalRef.current = DEFAULT_INTERVAL_SECONDS
      setCopied(false)
      setCopyFailed(false)
      setRetryNotice(null)
      setPhase('success')
      setError(null)

      const displayName =
        result.user?.display_name || result.user?.login || 'your Twitch account'
      setNotice(
        mode === 'login'
          ? `${result.created ? 'Account created. ' : ''}Signed in as ${displayName}.`
          : `Connected as ${displayName}. Your progress is syncing.`,
      )

      // `/auth/me` owns identity-change cache purging, exactly like the implicit
      // login path. A reconnect keeps the same identity, so its user-scoped
      // data is refreshed separately.
      try {
        await optionsRef.current.onConnected?.()
      } catch {
        // A UI callback must not turn a completed login into a failure.
      }
      await refresh()
      if (user) {
        await queryClient.invalidateQueries({ queryKey: ['u', user.id] })
      }
    },
    [mode, queryClient, refresh, setActiveFlow, user],
  )

  // The polling loop reads these refs so interval/slow_down and auth state
  // changes never restart the timer from zero.
  const finishWithErrorRef = useRef(finishWithError)
  const finishWithSuccessRef = useRef(finishWithSuccess)
  finishWithErrorRef.current = finishWithError
  finishWithSuccessRef.current = finishWithSuccess

  // Resume a pending flow after a reload or a trip through the Twitch app.
  useEffect(() => {
    if (resumedRef.current) return
    resumedRef.current = true

    const stored = readStoredFlow()
    if (!stored) return
    if (stored.mode !== mode) {
      // A reconnect flow must not silently sign someone in on the auth gate.
      clearStoredFlow()
      return
    }
    if (isExpired(stored.flow)) {
      clearStoredFlow()
      setPhase('error')
      setError(RESUME_EXPIRED_MESSAGE)
      return
    }

    intervalRef.current = stored.flow.interval
    setActiveFlow(stored.flow)
    setPhase('waiting')
  }, [mode, setActiveFlow])

  const flowId = flow?.flowId ?? null

  useEffect(() => {
    if (!flowId) return

    let cancelled = false
    let inFlight = false
    let timer: number | null = null
    let transientFailures = 0

    function schedule(seconds: number) {
      const delay = Math.max(1, Math.floor(seconds)) * 1000
      timer = window.setTimeout(() => {
        void tick()
      }, delay)
    }

    async function tick() {
      if (cancelled || inFlight) return
      const active = flowRef.current
      if (!active || active.flowId !== flowId) return
      if (isExpired(active)) {
        finishWithErrorRef.current(EXPIRED_MESSAGE)
        return
      }

      inFlight = true
      try {
        const result = await api.pollTwitchDevice(flowId)
        if (cancelled) return

        if (isPending(result)) {
          transientFailures = 0
          setRetryNotice(null)
          const nextInterval =
            normalizeInterval(result.interval) ?? intervalRef.current
          intervalRef.current = nextInterval
          const updated = { ...active, interval: nextInterval }
          setActiveFlow(updated)
          persistFlow(updated, mode)
          schedule(nextInterval)
          return
        }

        await finishWithSuccessRef.current(result)
      } catch (err) {
        if (cancelled) return
        if (
          isTransientPollError(err) &&
          transientFailures < MAX_TRANSIENT_POLL_RETRIES
        ) {
          // A 502/503/504 is usually a proxy blip, not a dead flow. Keep the
          // sessionStorage record and retry on the current cadence.
          transientFailures += 1
          setRetryNotice(TRANSIENT_RETRY_MESSAGE)
          schedule(intervalRef.current)
          return
        }
        finishWithErrorRef.current(pollErrorMessage(err))
      } finally {
        inFlight = false
      }
    }

    schedule(intervalRef.current)

    return () => {
      cancelled = true
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [flowId, mode, setActiveFlow])

  // Local expiry mirrors the server TTL so a sleeping tab does not wait forever.
  useEffect(() => {
    if (!flow?.expiresAt) return
    const expiresAt = new Date(flow.expiresAt).getTime()
    if (!Number.isFinite(expiresAt)) return

    const remaining = expiresAt - Date.now()
    if (remaining <= 0) {
      finishWithErrorRef.current(EXPIRED_MESSAGE)
      return
    }

    const timer = window.setTimeout(
      () => finishWithErrorRef.current(EXPIRED_MESSAGE),
      Math.min(remaining + 250, 2_147_000_000),
    )
    return () => window.clearTimeout(timer)
  }, [flow?.expiresAt])

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current)
      }
    }
  }, [])

  const start = useCallback(async () => {
    // A waiting flow must be cancelled before another one starts, otherwise the
    // old flow id is dropped from memory while it is still pending at Twitch.
    if (startingRef.current || flowRef.current) return
    startingRef.current = true
    setStarting(true)
    setError(null)
    setNotice(null)
    setCopied(false)
    setCopyFailed(false)
    setRetryNotice(null)
    setPhase('starting')

    try {
      const invite = inviteCode.trim()
      const info = await api.startTwitchDevice(invite || undefined)
      const next = toDeviceFlow(info)
      intervalRef.current = next.interval
      setActiveFlow(next)
      persistFlow(next, mode)
      setPhase('waiting')
    } catch (err) {
      setPhase('error')
      setError(startErrorMessage(err))
    } finally {
      setStarting(false)
      startingRef.current = false
    }
  }, [inviteCode, mode, setActiveFlow])

  const cancel = useCallback(async () => {
    const active = flowRef.current
    clearStoredFlow()
    setActiveFlow(null)
    intervalRef.current = DEFAULT_INTERVAL_SECONDS
    setPhase('idle')
    setError(null)
    setNotice(null)
    setCopied(false)
    setCopyFailed(false)
    setRetryNotice(null)
    if (!active) return

    setCanceling(true)
    try {
      await api.cancelTwitchDevice(active.flowId)
    } catch {
      // Cancelling is best effort; the unused flow expires server-side.
    } finally {
      setCanceling(false)
    }
  }, [setActiveFlow])

  const copyCode = useCallback(async () => {
    const active = flowRef.current
    if (!active) return

    const copiedOk = await copyText(active.userCode)
    setCopied(copiedOk)
    setCopyFailed(!copiedOk)

    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current)
    }
    copyTimerRef.current = window.setTimeout(() => {
      setCopied(false)
      setCopyFailed(false)
      copyTimerRef.current = null
    }, COPY_FEEDBACK_MS)
  }, [])

  return {
    flow,
    phase,
    inviteCode,
    inviteRequired,
    mode,
    starting,
    canceling,
    copied,
    copyFailed,
    error,
    notice,
    retryNotice,
    start,
    cancel,
    copyCode,
    setInviteCode,
  }
}

interface DeviceConnectProps {
  connect: DeviceConnectController
  /** Hide the built-in start button when the page already owns the action. */
  showStart?: boolean
  className?: string
}

export function DeviceConnect({
  connect,
  showStart = true,
  className,
}: DeviceConnectProps) {
  const verificationUrl = safeExternalUrl(connect.flow?.verificationUri)
  const waiting = connect.flow !== null
  const showInvite = connect.inviteRequired && !waiting

  return (
    <div className={`device-connect${className ? ` ${className}` : ''}`}>
      {connect.notice && (
        <p className="alert alert-success" role="status">
          <Icon name="check" size={16} />
          <span>{connect.notice}</span>
        </p>
      )}

      {connect.error && (
        <div className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{connect.error}</span>
          <button
            type="button"
            className="btn btn-secondary btn-sm device-alert-action"
            onClick={connect.start}
            disabled={connect.starting}
          >
            <Icon name="refresh" size={14} />
            {connect.starting ? 'Starting…' : 'Start a new code'}
          </button>
        </div>
      )}

      {showStart && !waiting && connect.phase !== 'success' && (
        <div className="device-start">
          {showInvite && (
            <div className="invite-field">
              <label className="field-label" htmlFor="device-invite-code">
                Invite code
              </label>
              <input
                id="device-invite-code"
                className="search-input"
                type="text"
                value={connect.inviteCode}
                onChange={(event) => connect.setInviteCode(event.target.value)}
                placeholder="Ask the admin for the invite code"
                autoComplete="off"
                spellCheck={false}
                disabled={connect.starting}
              />
              <p className="muted small">
                Only needed when creating a new account. Existing accounts can sign
                in without one.
              </p>
            </div>
          )}

          <button
            type="button"
            className="btn btn-primary"
            onClick={connect.start}
            disabled={connect.starting}
          >
            <Icon name="twitch" size={16} />
            {connect.starting ? 'Starting…' : 'Connect with code'}
          </button>
          <p className="muted small">
            Shows a short code to enter at <code>twitch.tv/activate</code>. No
            password or token copy needed.
          </p>
        </div>
      )}

      {connect.flow && (
        <div className="device-flow">
          <p className="alert alert-danger" role="note">
            <Icon name="alert" size={16} />
            <span>
              <strong>Only enter a code you generated in this app.</strong>{' '}
              Never enter a code someone sent you.
            </span>
          </p>

          <p className="field-label">Enter this code on Twitch</p>

          <div className="device-code-row">
            <code className="device-code">{connect.flow.userCode}</code>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={connect.copyCode}
            >
              <Icon name={connect.copied ? 'check' : 'copy'} size={14} />
              {connect.copied ? 'Copied' : 'Copy code'}
            </button>
          </div>

          <p className="device-instructions">
            {verificationUrl ? (
              <a
                href={verificationUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open {connect.flow.verificationUri.replace(/^https?:\/\//, '')}
              </a>
            ) : (
              <code>{connect.flow.verificationUri}</code>
            )}
            , enter the code, and approve the device login.
          </p>

          <p className="alert alert-warning" role="status">
            <Icon name="clock" size={16} />
            <span>
              Waiting for Twitch approval… This page updates automatically.
              {connect.flow.expiresAt
                ? ` Code expires ${formatDateTime(connect.flow.expiresAt)}.`
                : ''}
            </span>
          </p>

          {connect.retryNotice && (
            <p className="alert alert-warning" role="status">
              <Icon name="alert" size={16} />
              <span>{connect.retryNotice}</span>
            </p>
          )}

          {connect.copyFailed && (
            <p className="alert alert-warning" role="status">
              <Icon name="alert" size={16} />
              <span>
                Could not copy automatically. Select the code above and copy it
                manually.
              </span>
            </p>
          )}

          <div className="form-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={connect.cancel}
              disabled={connect.canceling}
            >
              <Icon name="x" size={15} />
              {connect.canceling ? 'Cancelling…' : 'Cancel'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
