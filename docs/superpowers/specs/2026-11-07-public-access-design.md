# Public Access Design — Tailscale Funnel + Basic Auth

**Date:** 2026-11-07
**Status:** Approved by user request to "write a plan and boot it up"

## Intent

Make the Twitch Drops Manager reachable outside the VPN, for free, without
moving the backend, worker, or SQLite data off the Raspberry Pi.

## Approach

Expose the existing frontend nginx container on port `8282` through
**Tailscale Funnel**. Funnel provides a public HTTPS URL
(`https://pi.taile9ec1c.ts.net`) with no domain purchase and no router changes.
Because Funnel is public, protect the entire site (UI and `/api`) with
**HTTP Basic Auth** at nginx. The frontend proxies `/api` to the backend, so
only port `8282` needs to be exposed; the API port `8000` stays private.

## Alternatives considered

- **Cloudflare Tunnel + Access:** strongest auth and a custom domain, but a
  stable hostname requires a domain the user owns. Free only if that domain
  already exists.
- **Vercel:** good for the static frontend, but the FastAPI API, APScheduler
  worker, and SQLite volume do not fit serverless.
- **Tailscale Serve (private):** keeps the app private to the tailnet, so it
  does not satisfy "outside the VPN".

## Constraints

- Single-user homelab app; no account system.
- SQLite in the `twitch-drops-manager_drops_data` volume must stay on the Pi.
- The app is deployed from Git through Portainer; changes go through `main`
  and "Pull and redeploy".
- No secrets in the public repository.

## Security

- Basic Auth applies to every route, including `/api`.
- The htpasswd file is a host file mounted read-only into the frontend
  container; the hash is not committed.
- The plaintext password is stored only in the user's home directory, mode
  `600`.
- Funnel terminates TLS; credentials travel over HTTPS.

## Success Criteria

- `http://localhost:8282/` returns `401` without credentials and `200` with them.
- `https://pi.taile9ec1c.ts.net/` returns `401` without credentials and `200`
  with them.
- `/api/v1/health` works through the authenticated public URL.
- Existing Kuma Docker monitors and Homepage labels continue to work.
