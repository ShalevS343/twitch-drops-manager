from app.domain.parsing import (
    campaign_matches_stream,
    parse_campaign,
    parse_inventory,
    parse_rewards,
)


def test_parse_rewards_extracts_benefits():
    campaign = {
        "timeBasedDrops": [
            {
                "name": "Drop 1",
                "requiredMinutesWatched": 30,
                "benefitEdges": [{"benefit": {"name": "Skin"}}],
            }
        ]
    }

    assert parse_rewards(campaign) == [
        {"name": "Drop 1", "benefit_name": "Skin", "required_minutes": 30}
    ]


def test_campaign_matches_stream_without_restrictions():
    assert campaign_matches_stream(None, "someone") is True
    assert campaign_matches_stream({"isEnabled": False}, "someone") is True


def test_campaign_matches_stream_enforces_allowlist():
    allow = {"isEnabled": True, "channels": [{"name": "Allowed"}]}

    assert campaign_matches_stream(allow, "allowed") is True
    assert campaign_matches_stream(allow, "other") is False


def test_parse_campaign_builds_external_id_and_status():
    parsed = parse_campaign(
        {"id": 42, "name": "Test", "status": "active", "owner": {"name": "Pub"}},
        "Rust",
        1,
    )

    assert parsed["external_id"] == "Rust:42"
    assert parsed["status"] == "ACTIVE"
    assert parsed["owner_name"] == "Pub"
    assert parsed["game_id"] == 1


def test_parse_inventory_flattens_drops_and_progress():
    rows = parse_inventory(
        [
            {
                "id": "campaign-1",
                "name": "Test Campaign",
                "endAt": "2026-12-01T00:00:00Z",
                "game": {"displayName": "Rust", "boxArtURL": "art.jpg"},
                "timeBasedDrops": [
                    {
                        "id": "drop-1",
                        "name": "First",
                        "requiredMinutesWatched": 60,
                        "benefitEdges": [{"benefit": {"name": "Skin"}}],
                        "self": {
                            "currentMinutesWatched": 60,
                            "isClaimed": False,
                            "dropInstanceID": "instance-1",
                        },
                    },
                    {
                        "id": "drop-2",
                        "name": "Second",
                        "requiredMinutesWatched": 30,
                        "self": {
                            "currentMinutesWatched": 0,
                            "isClaimed": True,
                            "dropInstanceID": "instance-2",
                        },
                    },
                ],
            }
        ]
    )

    assert len(rows) == 2
    assert rows[0]["game_name"] == "Rust"
    assert rows[0]["benefits"] == ["Skin"]
    assert rows[0]["is_ready"] is True

    # Claimed drops always look complete, even when Twitch reports 0 minutes.
    assert rows[1]["is_claimed"] is True
    assert rows[1]["current_minutes"] == 30
    assert rows[1]["is_ready"] is False


def test_parse_inventory_handles_missing_self_edge():
    rows = parse_inventory(
        [
            {
                "id": "campaign-1",
                "name": "Campaign",
                "game": {"displayName": "Minecraft"},
                "timeBasedDrops": [
                    {"id": "drop-1", "name": "Drop", "requiredMinutesWatched": 15}
                ],
            }
        ]
    )

    assert rows[0]["current_minutes"] == 0
    assert rows[0]["is_claimed"] is False
    assert rows[0]["is_ready"] is False
