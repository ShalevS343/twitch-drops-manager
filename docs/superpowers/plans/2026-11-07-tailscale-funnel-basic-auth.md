# Tailscale Funnel + Basic Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the Twitch Drops Manager outside the VPN for free via Tailscale Funnel, protected by nginx basic auth.

**Architecture:** Keep the existing Compose stack on the Raspberry Pi. Add basic auth at the frontend nginx server block, mount a host-owned htpasswd file into the frontend container, redeploy the Git-based Portainer stack, then enable Funnel on local port `8282`.

**Tech Stack:** Docker Compose, nginx, Tailscale Funnel, Portainer Git stack, OpenSSL htpasswd (`apr1`).

**Spec:** `docs/superpowers/specs/2026-11-07-public-access-design.md`

## Global Constraints

- No secrets in the repository. The htpasswd hash and plaintext password live only on the Pi.
- Basic auth must cover both the UI and `/api`.
- Only port `8282` is exposed publicly; `8000` stays private.
- Deploy through the Git-based Portainer stack; do not edit the stack compose in Portainer.
- Configuration change: TDD's config-file exception applies. Verification is HTTP status checks with `curl`.

## Review Focus

- A request without credentials must never reach the UI or API.
- Credentials must work through both local nginx and the public Funnel URL.
- The htpasswd mount must not break nginx startup or the static asset cache rules.
- The API proxy must keep working behind basic auth.
- Existing Docker/Kuma/Homepage integrations must remain unaffected.

---

### Task 1: Add basic auth and host credential file

**Files:**
- Modify: `frontend/nginx.conf`
- Modify: `infra/docker-compose.yml`
- Create (host, not repo): `/home/server/twitch-drops-auth/htpasswd`
- Create (host, not repo): `/home/server/twitch-drops-auth/password.txt`

**Interfaces:**
- Produces: nginx realm `Twitch Drops Manager`, user `admin`, htpasswd path `/etc/nginx/.htpasswd` inside the container.

- [ ] **Step 1: Create the host credential files**

```bash
mkdir -p /home/server/twitch-drops-auth
PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
HASH="$(openssl passwd -apr1 "$PASSWORD")"
printf 'admin:%s\n' "$HASH" > /home/server/twitch-drops-auth/htpasswd
printf '%s\n' "$PASSWORD" > /home/server/twitch-drops-auth/password.txt
chmod 644 /home/server/twitch-drops-auth/htpasswd
chmod 600 /home/server/twitch-drops-auth/password.txt
```

Expected: `htpasswd` starts with `admin:$apr1$`; `password.txt` is mode `600`.

- [ ] **Step 2: Add the auth directive to nginx**

In `frontend/nginx.conf`, inside `server { ... }`, add:

```nginx
    auth_basic "Twitch Drops Manager";
    auth_basic_user_file /etc/nginx/.htpasswd;
```

Expected: every location, including `/api/`, inherits basic auth.

- [ ] **Step 3: Mount the htpasswd file in Compose**

Add to the `frontend` service in `infra/docker-compose.yml`:

```yaml
    volumes:
      - ${DROPS_AUTH_FILE:-/home/server/twitch-drops-auth/htpasswd}:/etc/nginx/.htpasswd:ro
```

Expected: `docker compose config` resolves the default host path.

- [ ] **Step 4: Verify with a temporary frontend container**

```bash
cd /opt/twitch-drops-manager/twitch-drops-manager
docker build -t twitch-drops-frontend:authtest frontend
docker run -d --rm --name tdm-auth-test -p 127.0.0.1:18282:80 \
  -v /home/server/twitch-drops-auth/htpasswd:/etc/nginx/.htpasswd:ro \
  twitch-drops-frontend:authtest
sleep 2
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18282/
curl -s -o /dev/null -w '%{http_code}\n' -u "admin:$(cat /home/server/twitch-drops-auth/password.txt)" http://127.0.0.1:18282/
docker rm -f tdm-auth-test
```

Expected: `401` without credentials, `200` with credentials.

- [ ] **Step 5: Commit and push**

```bash
git add frontend/nginx.conf infra/docker-compose.yml docs/superpowers
git commit -m "feat(infra): protect public frontend with basic auth"
git push origin main
```

### Task 2: Redeploy the Git stack

**Files:** none (deployment only)

- [ ] **Step 1: Trigger a Git redeploy in Portainer**

Call `PUT /api/stacks/10/git/redeploy?endpointId=3` with the stored stack env and `RepositoryReferenceName=refs/heads/main`.

Expected: HTTP `200`; stack `GitConfig.ConfigHash` equals the new `main` commit.

- [ ] **Step 2: Verify local auth and API proxy**

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8282/
curl -s -o /dev/null -w '%{http_code}\n' -u "admin:$(cat /home/server/twitch-drops-auth/password.txt)" http://localhost:8282/
curl -s -o /dev/null -w '%{http_code}\n' -u "admin:$(cat /home/server/twitch-drops-auth/password.txt)" http://localhost:8282/api/v1/health
```

Expected: `401`, `200`, `200`.

### Task 3: Enable Tailscale Funnel

**Files:** none

- [ ] **Step 1: Enable Funnel for local port 8282**

```bash
tailscale funnel 8282 on
tailscale funnel status
```

Expected: `https://pi.taile9ec1c.ts.net` proxies to `http://127.0.0.1:8282`.

- [ ] **Step 2: Verify the public URL**

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://pi.taile9ec1c.ts.net/
curl -s -o /dev/null -w '%{http_code}\n' -u "admin:$(cat /home/server/twitch-drops-auth/password.txt)" https://pi.taile9ec1c.ts.net/
curl -s -o /dev/null -w '%{http_code}\n' -u "admin:$(cat /home/server/twitch-drops-auth/password.txt)" https://pi.taile9ec1c.ts.net/api/v1/health
```

Expected: `401`, `200`, `200`.

### Task 4: Document the public access

**Files:**
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHANGELOG.md`

- [ ] **Step 1: Document Funnel, auth, and password rotation**

Add a "Public access" section to `docs/OPERATIONS.md`: Funnel URL, htpasswd path, password path, rotation command, and a warning that Funnel is public. Update `docs/STATUS.md` and add a dated changelog entry.

- [ ] **Step 2: Commit and push, then redeploy Git stack**

```bash
git add docs/OPERATIONS.md docs/STATUS.md docs/CHANGELOG.md
git commit -m "docs: record Tailscale Funnel public access"
git push origin main
```

Trigger the same Portainer Git redeploy so the stack hash matches `main`.

- [ ] **Step 3: Final verification**

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8282/
curl -s -o /dev/null -w '%{http_code}\n' -u "admin:$(cat /home/server/twitch-drops-auth/password.txt)" https://pi.taile9ec1c.ts.net/api/v1/health
docker ps --filter name=twitch-drops-manager
```

Expected: `401`; `200`; all three containers up.
