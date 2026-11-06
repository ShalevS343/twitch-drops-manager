from app.domain.parsing import campaign_matches_stream, parse_campaign, parse_rewards


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
