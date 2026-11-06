from sqlalchemy import inspect

from app.domain.models import Campaign, ProgressSnapshot


def test_campaign_raw_column_is_deferred():
    assert inspect(Campaign).attrs["raw"].deferred is True


def test_progress_snapshot_has_composite_drop_recorded_index():
    index_names = {index.name for index in ProgressSnapshot.__table__.indexes}
    assert "ix_progress_snapshots_drop_recorded" in index_names
