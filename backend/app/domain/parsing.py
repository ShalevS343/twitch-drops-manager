from typing import Any


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
