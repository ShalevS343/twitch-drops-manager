from sqlalchemy import CheckConstraint, inspect

from app.domain.models import (
    AppMeta,
    Campaign,
    ProgressSnapshot,
    TwitchAccount,
    User,
    UserCampaignCompletion,
    UserCampaignStart,
    UserDropProgress,
    UserGame,
    UserNotification,
    UserProgressSnapshot,
    UserSession,
    UserWatchFocus,
)


def _unique_column_sets(model) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }


def test_campaign_raw_column_is_deferred():
    assert inspect(Campaign).attrs["raw"].deferred is True


def test_progress_snapshot_has_composite_drop_recorded_index():
    index_names = {index.name for index in ProgressSnapshot.__table__.indexes}
    assert "ix_progress_snapshots_drop_recorded" in index_names


def test_user_twitch_user_id_is_unique():
    assert User.__table__.c.twitch_user_id.unique is True


def test_user_session_token_hash_is_unique():
    assert UserSession.__table__.c.token_hash.unique is True


def test_twitch_account_user_id_is_unique():
    assert TwitchAccount.__table__.c.user_id.unique is True


def test_user_game_unique_user_and_game():
    assert ("user_id", "game_id") in _unique_column_sets(UserGame)


def test_user_drop_progress_unique_user_and_drop():
    assert ("user_id", "drop_id") in _unique_column_sets(UserDropProgress)


def test_user_campaign_completion_unique_user_and_campaign():
    assert ("user_id", "campaign_gql_id") in _unique_column_sets(
        UserCampaignCompletion
    )


def test_user_notification_unique_user_and_dedupe_key():
    assert ("user_id", "dedupe_key") in _unique_column_sets(UserNotification)


def test_user_campaign_start_unique_user_and_external_id():
    assert ("user_id", "external_id") in _unique_column_sets(UserCampaignStart)


def test_user_watch_focus_has_no_singleton_check():
    checks = [
        constraint
        for constraint in UserWatchFocus.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert not any("id = 1" in str(check.sqltext) for check in checks)


def test_user_progress_snapshot_has_user_drop_recorded_index():
    index_names = {index.name for index in UserProgressSnapshot.__table__.indexes}
    assert "ix_user_progress_snapshots_user_drop_recorded" in index_names


def test_app_meta_key_is_primary_key():
    assert AppMeta.__table__.c.key.primary_key is True
