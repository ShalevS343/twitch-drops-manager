from datetime import datetime, timezone
from typing import Any


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating ``Z`` and naive values."""
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def campaign_gql_id_from_external_id(external_id: str | None) -> str:
    """Extract Twitch's campaign GQL id from ``f"{game}:{gql_id}"``."""
    return (external_id or "").rsplit(":", 1)[-1]


def game_name(game: dict[str, Any]) -> str:
    return str(game.get("gameDisplayName") or game.get("name") or "").strip()


def game_twitch_id(game: dict[str, Any]) -> str | None:
    value = game.get("gameId") or game.get("id")
    return str(value) if value else None


def campaigns_of(game: dict[str, Any]) -> list[dict[str, Any]]:
    raw = game.get("campaigns")
    if raw is None:
        raw = game.get("rewards")
    if not isinstance(raw, list):
        return []
    return [campaign for campaign in raw if isinstance(campaign, dict)]


def campaign_external_id(campaign: dict[str, Any], game: str) -> str:
    value = campaign.get("id") or campaign.get("campaignId")
    if value is not None:
        return f"{game}:{value}"
    return f"{game}:{campaign.get('name') or 'unknown'}"


def parse_rewards(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    drops = campaign.get("timeBasedDrops")
    rewards: list[dict[str, Any]] = []
    if not isinstance(drops, list):
        return rewards

    for drop in drops:
        if not isinstance(drop, dict):
            continue

        benefit_names: list[str] = []
        edges = drop.get("benefitEdges")
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                benefit = edge.get("benefit")
                if isinstance(benefit, dict) and benefit.get("name"):
                    benefit_names.append(str(benefit["name"]))

        try:
            minutes = int(drop.get("requiredMinutesWatched") or 0)
        except (TypeError, ValueError):
            minutes = 0

        rewards.append(
            {
                "name": str(drop.get("name") or "Reward"),
                "benefit_name": ", ".join(benefit_names),
                "required_minutes": minutes,
            }
        )

    return rewards


def parse_campaign(campaign: dict[str, Any], game: str, game_id: int) -> dict[str, Any]:
    owner = campaign.get("owner")
    owner_name = owner.get("name", "") if isinstance(owner, dict) else ""
    allow = campaign.get("allow")
    starts_at = campaign.get("startAt")
    ends_at = campaign.get("endAt")

    return {
        "external_id": campaign_external_id(campaign, game),
        "game_id": game_id,
        "name": str(campaign.get("name") or "Unknown campaign"),
        "status": str(campaign.get("status") or "").upper(),
        "starts_at": str(starts_at) if starts_at is not None else None,
        "ends_at": str(ends_at) if ends_at is not None else None,
        "details_url": str(campaign.get("detailsURL") or ""),
        "owner_name": str(owner_name),
        "allow": allow if isinstance(allow, dict) else None,
        "raw": campaign,
        "rewards": parse_rewards(campaign),
    }


def campaign_matches_stream(allow: Any, user_login: str) -> bool:
    if not isinstance(allow, dict):
        return True
    if not allow.get("isEnabled", False):
        return True

    channels = allow.get("channels", [])
    if not isinstance(channels, list):
        return False

    allowed = set()
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        name = channel.get("name") or channel.get("login") or ""
        if name:
            allowed.add(str(name).casefold())

    return user_login.casefold() in allowed


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_earned_rewards(inventory: dict[str, Any]) -> dict[str, set[str]]:
    """Map campaign GQL id -> claimed reward ids from ``earnedDropRewards``.

    Twitch only returns this block when ``fetchRewardCampaigns`` is true. It is
    the source of truth for campaigns that have already left
    ``dropCampaignsInProgress``.
    """
    earned = inventory.get("earnedDropRewards")
    edges = earned.get("edges") if isinstance(earned, dict) else None
    if not isinstance(edges, list):
        return {}

    claimed: dict[str, set[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if not isinstance(node, dict) or node.get("status") != "CLAIMED":
            continue

        campaign = node.get("campaign")
        campaign_id = (
            str(campaign.get("id") or "") if isinstance(campaign, dict) else ""
        )
        if not campaign_id:
            continue

        item = node.get("item")
        item_id = (
            str(item.get("id") or "") if isinstance(item, dict) else ""
        ) or str(node.get("id") or "")
        if item_id:
            claimed.setdefault(campaign_id, set()).add(item_id)

    return claimed


def parse_inventory(campaigns: list[Any]) -> list[dict[str, Any]]:
    """Flatten Twitch's ``dropCampaignsInProgress`` into per-drop progress rows."""
    rows: list[dict[str, Any]] = []

    for campaign in campaigns:
        if not isinstance(campaign, dict):
            continue

        game = campaign.get("game") if isinstance(campaign.get("game"), dict) else {}
        drops = campaign.get("timeBasedDrops")
        if not isinstance(drops, list):
            continue

        for drop in drops:
            if not isinstance(drop, dict):
                continue

            drop_id = str(drop.get("id") or "")
            if not drop_id:
                continue

            own = drop.get("self") if isinstance(drop.get("self"), dict) else {}
            required = _as_int(drop.get("requiredMinutesWatched"))
            current = _as_int(own.get("currentMinutesWatched"))
            claimed = bool(own.get("isClaimed"))

            # Twitch reports inconsistent minutes for claimed drops; treat them
            # as complete so the UI doesn't show a claimed drop at 40%.
            if claimed:
                current = required

            benefits: list[str] = []
            edges = drop.get("benefitEdges")
            if isinstance(edges, list):
                for edge in edges:
                    if not isinstance(edge, dict):
                        continue
                    benefit = edge.get("benefit")
                    if isinstance(benefit, dict) and benefit.get("name"):
                        benefits.append(str(benefit["name"]))

            rows.append(
                {
                    "drop_id": drop_id,
                    "drop_name": str(drop.get("name") or "Drop"),
                    "drop_instance_id": own.get("dropInstanceID") or None,
                    "campaign_gql_id": str(campaign.get("id") or ""),
                    "campaign_name": str(campaign.get("name") or "Unknown campaign"),
                    "campaign_ends_at": (
                        str(campaign.get("endAt")) if campaign.get("endAt") else None
                    ),
                    "game_name": str(game.get("displayName") or game.get("name") or ""),
                    "game_box_art_url": str(game.get("boxArtURL") or ""),
                    "starts_at": str(drop.get("startAt")) if drop.get("startAt") else None,
                    "ends_at": str(drop.get("endAt")) if drop.get("endAt") else None,
                    "required_minutes": required,
                    "current_minutes": current,
                    "is_claimed": claimed,
                    "is_ready": required > 0 and current >= required and not claimed,
                    "benefits": benefits,
                }
            )

    return rows
