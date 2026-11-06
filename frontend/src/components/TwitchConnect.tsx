import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'

import { api } from '../api/client'
import type { TwitchConnect as TwitchConnectInfo } from '../api/types'
import { Icon } from './ui/Icon'

export interface TwitchConnectController {
  connect: TwitchConnectInfo | null
  redirectUrl: string
  starting: boolean
  saving: boolean
  error: string | null
  notice: string | null
  start: () => Promise<void>
  save: (event: FormEvent<HTMLFormElement>) => Promise<void>
  cancel: () => void
  setRedirectUrl: (value: string) => void
}

export function useTwitchConnect(): TwitchConnectController {
  const queryClient = useQueryClient()

  const [connect, setConnect] = useState<TwitchConnectInfo | null>(null)
  const [redirectUrl, setRedirectUrl] = useState('')
  const [starting, setStarting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const start = useCallback(async () => {
    setStarting(true)
    setError(null)
    setNotice(null)
    try {
      const info = await api.twitchConnectUrl()
      setConnect(info)
      window.open(info.authorize_url, '_blank', 'noopener,noreferrer')
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
        const result = await api.twitchConnect(redirectUrl)
        setConnect(null)
        setRedirectUrl('')
        setNotice(
          result.message ??
            `Connected as ${result.login ?? 'Twitch user'}. Your progress is syncing.`,
        )
        await queryClient.invalidateQueries()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not save the Twitch token')
      } finally {
        setSaving(false)
      }
    },
    [queryClient, redirectUrl],
  )

  const cancel = useCallback(() => {
    setConnect(null)
    setRedirectUrl('')
    setError(null)
  }, [])

  return {
    connect,
    redirectUrl,
    starting,
    saving,
    error,
    notice,
    start,
    save,
    cancel,
    setRedirectUrl,
  }
}

export function TwitchConnect({ connect }: { connect: TwitchConnectController }) {
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
              <a href={connect.connect.authorize_url} target="_blank" rel="noreferrer">
                Authorize this app on Twitch
              </a>{' '}
              (opens in a new tab), then click <strong>Authorize</strong>.
            </li>
            <li>
              Twitch sends you to <code>twitch.tv/#access_token=…</code>. Copy the{' '}
              <strong>entire URL</strong> from the address bar.
            </li>
            <li>Paste it below and save.</li>
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
            <div className="form-actions">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={connect.saving || !connect.redirectUrl.trim()}
              >
                {connect.saving ? 'Saving…' : 'Save connection'}
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
