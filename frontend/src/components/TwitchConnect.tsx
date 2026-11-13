import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'

import { api } from '../api/client'
import type { TwitchConnect as TwitchConnectInfo, TwitchLoginResult } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { safeExternalUrl } from '../lib/url'
import { Icon } from './ui/Icon'

export type TwitchConnectMode = 'login' | 'reconnect'

export interface TwitchConnectOptions {
  /** Sign-in gate copy and behaviour; defaults to reconnecting an existing user. */
  mode?: TwitchConnectMode
  /** Ask for the shared invite code before submitting. */
  inviteRequired?: boolean
  /** Override the connect call, e.g. to route through the auth provider. */
  authenticate?: (
    redirectUrl: string,
    inviteCode?: string,
  ) => Promise<TwitchLoginResult>
  /** Runs after a successful connection, before caches are invalidated. */
  onConnected?: () => void | Promise<unknown>
}

export interface TwitchConnectController {
  connect: TwitchConnectInfo | null
  redirectUrl: string
  inviteCode: string
  inviteRequired: boolean
  mode: TwitchConnectMode
  starting: boolean
  saving: boolean
  error: string | null
  notice: string | null
  start: () => Promise<void>
  save: (event: FormEvent<HTMLFormElement>) => Promise<void>
  cancel: () => void
  setRedirectUrl: (value: string) => void
  setInviteCode: (value: string) => void
}

export function useTwitchConnect(
  options: TwitchConnectOptions = {},
): TwitchConnectController {
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const mode = options.mode ?? 'reconnect'
  const inviteRequired = options.inviteRequired ?? false
  const { authenticate, onConnected } = options

  const [connect, setConnect] = useState<TwitchConnectInfo | null>(null)
  const [redirectUrl, setRedirectUrl] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [starting, setStarting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const start = useCallback(async () => {
    setStarting(true)
    setError(null)
    setNotice(null)
    try {
      const info = await api.twitchAuthorize()
      const authorizeUrl = safeExternalUrl(info.authorize_url)
      if (!authorizeUrl) {
        setError('The server returned an unsafe Twitch authorization URL.')
        return
      }
      setConnect(info)
      window.open(authorizeUrl, '_blank', 'noopener,noreferrer')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Twitch login')
    } finally {
      setStarting(false)
    }
  }, [])

  const save = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      setSaving(true)
      setError(null)
      try {
        const submit = authenticate ?? api.twitchConnect
        const result = await submit(redirectUrl.trim(), inviteCode.trim() || undefined)
        setConnect(null)
        setRedirectUrl('')
        setInviteCode('')
        const displayName =
          result.user?.display_name || result.user?.login || 'your Twitch account'
        setNotice(
          mode === 'login'
            ? `${result.created ? 'Account created. ' : ''}Signed in as ${displayName}.`
            : `Connected as ${displayName}. Your progress is syncing.`,
        )
        await onConnected?.()
        // Identity changes purge everything through the auth provider; a
        // reconnect only needs to refresh this user's own data.
        if (user) {
          await queryClient.invalidateQueries({ queryKey: ['u', user.id] })
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not save the Twitch token')
      } finally {
        setSaving(false)
      }
    },
    [authenticate, inviteCode, mode, onConnected, queryClient, redirectUrl, user],
  )

  const cancel = useCallback(() => {
    setConnect(null)
    setRedirectUrl('')
    setInviteCode('')
    setError(null)
  }, [])

  return {
    connect,
    redirectUrl,
    inviteCode,
    inviteRequired,
    mode,
    starting,
    saving,
    error,
    notice,
    start,
    save,
    cancel,
    setRedirectUrl,
    setInviteCode,
  }
}

/**
 * Keeps the legacy implicit authorize/paste flow available without competing
 * with the code flow for attention. Used by Profile and Settings.
 */
export function TwitchConnectAdvanced({
  connect,
  disabled = false,
}: {
  connect: TwitchConnectController
  disabled?: boolean
}) {
  return (
    <details className="advanced-connect">
      <summary>Advanced / desktop: paste a Twitch URL instead</summary>
      <div className="advanced-connect-body">
        <p className="muted small">
          Use this fallback only if the code screen is unavailable. It opens
          Twitch in a new tab and asks you to paste the redirect URL.
        </p>
        <div className="auth-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={connect.start}
            disabled={connect.starting || disabled}
          >
            <Icon name="twitch" size={16} />
            {connect.starting
              ? 'Opening Twitch…'
              : connect.connect
                ? 'Reopen Twitch authorization'
                : 'Continue with Twitch URL'}
          </button>
        </div>

        <TwitchConnect connect={connect} />
      </div>
    </details>
  )
}

export function TwitchConnect({ connect }: { connect: TwitchConnectController }) {
  const isLogin = connect.mode === 'login'
  const authorizeUrl = safeExternalUrl(connect.connect?.authorize_url)

  return (
    <>
      {connect.notice && (
        <p className="alert alert-success" role="status">
          <Icon name="check" size={16} />
          <span>{connect.notice}</span>
        </p>
      )}

      {connect.error && (
        <p className="alert alert-danger" role="alert">
          <Icon name="alert" size={16} />
          <span>{connect.error}</span>
        </p>
      )}

      {connect.connect && (
        <div className="connect-box">
          <ol className="connect-steps">
            <li>
              {authorizeUrl ? (
                <a href={authorizeUrl} target="_blank" rel="noopener noreferrer">
                  Authorize this app on Twitch
                </a>
              ) : (
                <span>Authorize this app on Twitch</span>
              )}{' '}
              (opens in a new tab), then click <strong>Authorize</strong>.
            </li>
            <li>
              Twitch sends you to <code>twitch.tv/#access_token=…</code>. Copy the{' '}
              <strong>entire URL</strong> from the address bar.
            </li>
            <li>
              {isLogin
                ? 'Paste it below, add an invite code if one is required, then sign in.'
                : 'Paste it below and save.'}
            </li>
          </ol>

          <form onSubmit={connect.save}>
            <label className="field-label" htmlFor="twitch-redirect-url">
              Twitch redirect URL
            </label>
            <textarea
              id="twitch-redirect-url"
              className="textarea redirect-input"
              rows={3}
              value={connect.redirectUrl}
              onChange={(event) => connect.setRedirectUrl(event.target.value)}
              placeholder="https://www.twitch.tv/#access_token=..."
              spellCheck={false}
            />

            {connect.inviteRequired && (
              <div className="invite-field">
                <label className="field-label" htmlFor="twitch-invite-code">
                  Invite code
                </label>
                <input
                  id="twitch-invite-code"
                  className="search-input"
                  type="text"
                  value={connect.inviteCode}
                  onChange={(event) => connect.setInviteCode(event.target.value)}
                  placeholder="Ask the admin for the invite code"
                  autoComplete="off"
                  spellCheck={false}
                />
                <p className="muted small">
                  Only needed when creating a new account. Existing accounts can sign
                  in without one.
                </p>
              </div>
            )}

            <div className="form-actions">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={connect.saving || !connect.redirectUrl.trim()}
              >
                {connect.saving
                  ? isLogin
                    ? 'Signing in…'
                    : 'Saving…'
                  : isLogin
                    ? 'Sign in with Twitch'
                    : 'Save Twitch connection'}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={connect.cancel}
                disabled={connect.saving}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  )
}
