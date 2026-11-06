import re
import secrets
import urllib.parse
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import NotConfiguredError, ProviderError

AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"

# Twitch's GQL API rejects tokens issued to third-party clients, so the login
# uses Twitch's own Android app client (the same approach as TwitchDropsMiner).
ANDROID_USER_AGENT = (
    "Dalvik/2.1.0 (Linux; U; Android 16; SM-S911B Build/TP1A.220624.014) "
    "tv.twitch.android.app/31.8.0/3108006"
)

# Twitch's own Drops page uses this persisted GraphQL query. The hash can be
# rotated by Twitch at any time; when it stops working we fall back to the
# equivalent raw query below.
INVENTORY_HASH = "8337eb8541b314040b0edde0c09c5c7a2783ba1960aa9edfbf3bac16d0fec404"

INVENTORY_QUERY = """
query Inventory($fetchRewardCampaigns: Boolean) {
  currentUser {
    inventory {
      dropCampaignsInProgress {
        id
        name
        status
        startAt
        endAt
        accountLinkURL
        imageURL
        self { isAccountConnected }
        game { id name displayName boxArtURL }
        allow { isEnabled channels { name } }
        timeBasedDrops {
          id
          name
          requiredMinutesWatched
          startAt
          endAt
          preconditionDrops { id }
          benefitEdges { benefit { id name imageAssetURL } }
          self { dropInstanceID isClaimed currentMinutesWatched }
        }
      }
      gameEventDrops { id lastAwardedAt }
    }
  }
}
"""


class TwitchUserProvider:
    """Twitch user-context access for read-only drops progress.

    The official Helix API has no drops-progress endpoint, so this provider uses
    the same internal GraphQL query as Twitch's Drops page. It never mutates the
    account (no claiming, no watching).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._session_id = secrets.token_hex(8)
        self._device_id = secrets.token_hex(16)

    @property
    def ready(self) -> bool:
        return bool(self.settings.twitch_device_client_id)

    @property
    def authorize_url(self) -> str:
        """URL the user opens to grant read access (implicit grant flow)."""
        query = urllib.parse.urlencode(
            {
                "client_id": self.settings.twitch_device_client_id,
                "redirect_uri": self.settings.twitch_oauth_redirect_uri,
                "response_type": "token",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    @staticmethod
    def parse_oauth_token(value: str) -> str | None:
        """Extract a token from a pasted redirect URL, query string, or raw token."""
        value = (value or "").strip()
        if not value:
            return None

        if "access_token=" in value:
            if "#" in value:
                query = value.split("#", 1)[1]
            else:
                query = urllib.parse.urlparse(value).query
            token = urllib.parse.parse_qs(query).get("access_token", [None])[0]
            if token:
                return token.strip()

        if re.fullmatch(r"[A-Za-z0-9]{20,}", value):
            return value

        return None

    async def validate(self, access_token: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    VALIDATE_URL,
                    headers={"Authorization": f"OAuth {access_token}"},
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Twitch token validation failed: {exc}") from exc

        if response.status_code == 401:
            raise NotConfiguredError("Twitch login is invalid or expired")
        if response.status_code >= 400:
            raise ProviderError(f"Twitch token validation failed ({response.status_code})")

        return response.json()

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        self._require_ready()

        data = {
            "client_id": self.settings.twitch_device_client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if self.settings.twitch_device_client_secret:
            data["client_secret"] = self.settings.twitch_device_client_secret

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(TOKEN_URL, data=data)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Twitch token refresh failed: {exc}") from exc

        if response.status_code in (400, 401):
            raise NotConfiguredError("Twitch login expired; reconnect your account")
        if response.status_code >= 400:
            raise ProviderError(
                f"Twitch token refresh failed ({response.status_code}): {response.text[:200]}"
            )

        return response.json()

    async def fetch_inventory(self, access_token: str) -> dict[str, Any]:
        data = await self._gql(access_token)

        current_user = data.get("currentUser") if isinstance(data, dict) else None
        inventory = (
            current_user.get("inventory") if isinstance(current_user, dict) else None
        )
        if not isinstance(inventory, dict):
            raise ProviderError("Unexpected Twitch inventory response")

        return inventory

    def _require_ready(self) -> None:
        if not self.ready:
            raise NotConfiguredError("Twitch progress client is not configured")

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Client-Id": self.settings.gql_client_id,
            "Authorization": f"OAuth {access_token}",
            "User-Agent": ANDROID_USER_AGENT,
            "Client-Session-Id": self._session_id,
            "X-Device-Id": self._device_id,
            "Origin": "https://www.twitch.tv",
            "Referer": "https://www.twitch.tv/",
            "Content-Type": "application/json",
        }

    async def _gql(self, access_token: str) -> dict[str, Any]:
        self._require_ready()
        headers = self._headers(access_token)

        payload = {
            "operationName": "Inventory",
            "variables": {"fetchRewardCampaigns": False},
            "extensions": {
                "persistedQuery": {"version": 1, "sha256Hash": INVENTORY_HASH}
            },
        }

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(
                    self.settings.twitch_gql_url, headers=headers, json=payload
                )

                body: dict[str, Any] = {}
                try:
                    body = response.json()
                except ValueError:
                    body = {}

                if self._persisted_query_missing(body):
                    fallback = {
                        "operationName": "Inventory",
                        "query": INVENTORY_QUERY,
                        "variables": {"fetchRewardCampaigns": False},
                    }
                    response = await client.post(
                        self.settings.twitch_gql_url, headers=headers, json=fallback
                    )
                    try:
                        body = response.json()
                    except ValueError:
                        body = {}
        except httpx.HTTPError as exc:
            raise ProviderError(f"Twitch GraphQL request failed: {exc}") from exc

        if response.status_code == 401:
            raise NotConfiguredError(
                "Twitch rejected the saved token; reconnect your account"
            )
        if response.status_code == 429:
            raise ProviderError("Twitch GraphQL rate limit reached; try again later")
        if response.status_code >= 400:
            raise ProviderError(f"Twitch GraphQL request failed ({response.status_code})")

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            errors = body.get("errors") if isinstance(body, dict) else None
            message = ""
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict):
                    message = str(first.get("message") or "")
            raise ProviderError(f"Twitch GraphQL error: {message or 'empty response'}")

        return data

    @staticmethod
    def _persisted_query_missing(body: Any) -> bool:
        if not isinstance(body, dict):
            return False
        errors = body.get("errors")
        if not isinstance(errors, list):
            return False
        return any(
            "PersistedQueryNotFound" in str(error.get("message", ""))
            for error in errors
            if isinstance(error, dict)
        )
