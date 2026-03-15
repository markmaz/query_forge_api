"""
tests/test_data_freshness_check.py

Tests for DataFreshnessCheckSkill.
Run with: pytest tests/test_data_freshness_check.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.skills.base import QueryMetadata, SkillContext
from app.skills.data_freshness_check import DataFreshnessCheckSkill
from app.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def skill():
    return DataFreshnessCheckSkill()


@pytest.fixture()
def metadata():
    return QueryMetadata(
        query_id=20,
        query_name="Orders Pipeline",
        column_names=["order_id", "created_at", "status"],
        column_types={"order_id": "int", "created_at": "str", "status": "str"},
        row_count=50,
        execution_time_ms=30,
        executed_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def now():
    return datetime.now(timezone.utc)


@pytest.fixture()
def sample_rows(now):
    return [
        {
            "order_id": i,
            "created_at": (now - timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"),
            "status": "active",
        }
        for i in range(1, 6)
    ]


def make_context(metadata, rows, config, snapshot=None):
    ctx = SkillContext(
        query_id=20,
        workspace_id=2,
        triggered_by="schedule",
        results=rows,
        metadata=metadata,
        config=config,
    )
    return ctx


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_skill_registered():
    assert SkillRegistry.exists("data_freshness_check")


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_validate_valid(skill):
    errors = skill.validate_config({
        "checks": [{"type": "no_rows"}],
        "channels": [{"type": "slack", "webhook_url": "https://hooks.slack.com/x"}],
    })
    assert errors == []


def test_validate_no_checks(skill):
    errors = skill.validate_config({
        "checks": [],
        "channels": [{"type": "slack", "webhook_url": "https://x.com"}],
    })
    assert any("check" in e.lower() for e in errors)


def test_validate_timestamp_stale_missing_column(skill):
    errors = skill.validate_config({
        "checks": [{"type": "timestamp_stale"}],
        "channels": [{"type": "slack", "webhook_url": "https://x.com"}],
    })
    assert any("column" in e.lower() for e in errors)


def test_validate_fixed_window_missing_hours(skill):
    errors = skill.validate_config({
        "checks": [{"type": "no_new_rows", "window_mode": "fixed", "fixed_hours": 0}],
        "channels": [{"type": "slack", "webhook_url": "https://x.com"}],
    })
    assert any("fixed_hours" in e.lower() or "positive" in e.lower() for e in errors)


def test_validate_missing_channel_webhook(skill):
    errors = skill.validate_config({
        "checks": [{"type": "no_rows"}],
        "channels": [{"type": "teams"}],
    })
    assert any("webhook" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# no_rows check
# ---------------------------------------------------------------------------


def test_no_rows_stale_when_empty(skill, metadata):
    empty_meta = QueryMetadata(**{**metadata.__dict__, "row_count": 0})
    ctx = make_context(empty_meta, [], {"checks": [], "channels": []})
    result = skill._check_no_rows(ctx)
    assert result["stale"] is True


def test_no_rows_fresh_when_rows_exist(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    result = skill._check_no_rows(ctx)
    assert result["stale"] is False


# ---------------------------------------------------------------------------
# no_new_rows check — relative mode
# ---------------------------------------------------------------------------


def test_no_new_rows_relative_stale_when_count_unchanged(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "no_new_rows", "window_mode": "relative"}
    last_snapshot = {"row_count": 50}  # same as current
    result = skill._check_no_new_rows(check, ctx, last_snapshot, datetime.now(timezone.utc))
    assert result["stale"] is True


def test_no_new_rows_relative_fresh_when_count_increased(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "no_new_rows", "window_mode": "relative"}
    last_snapshot = {"row_count": 30}  # fewer than current 50
    result = skill._check_no_new_rows(check, ctx, last_snapshot, datetime.now(timezone.utc))
    assert result["stale"] is False


def test_no_new_rows_relative_fresh_when_no_baseline(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "no_new_rows", "window_mode": "relative"}
    result = skill._check_no_new_rows(check, ctx, None, datetime.now(timezone.utc))
    assert result["stale"] is False
    assert "baseline" in result["message"].lower()


# ---------------------------------------------------------------------------
# no_new_rows check — fixed mode
# ---------------------------------------------------------------------------


def test_no_new_rows_fixed_stale_when_window_exceeded(skill, metadata, sample_rows, now):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "no_new_rows", "window_mode": "fixed", "fixed_hours": 24}
    old_change = (now - timedelta(hours=30)).isoformat()
    result = skill._check_no_new_rows(check, ctx, {"last_row_count_change_at": old_change}, now)
    assert result["stale"] is True
    assert result["hours_since_change"] > 24


def test_no_new_rows_fixed_fresh_within_window(skill, metadata, sample_rows, now):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "no_new_rows", "window_mode": "fixed", "fixed_hours": 24}
    recent_change = (now - timedelta(hours=6)).isoformat()
    result = skill._check_no_new_rows(check, ctx, {"last_row_count_change_at": recent_change}, now)
    assert result["stale"] is False


# ---------------------------------------------------------------------------
# row_count_unchanged check
# ---------------------------------------------------------------------------


def test_row_count_unchanged_stale_when_identical(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "row_count_unchanged", "window_mode": "relative"}
    result = skill._check_row_count_unchanged(check, ctx, {"row_count": 50}, datetime.now(timezone.utc))
    assert result["stale"] is True


def test_row_count_unchanged_fresh_when_changed(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "row_count_unchanged", "window_mode": "relative"}
    result = skill._check_row_count_unchanged(check, ctx, {"row_count": 45}, datetime.now(timezone.utc))
    assert result["stale"] is False


# ---------------------------------------------------------------------------
# timestamp_stale check
# ---------------------------------------------------------------------------


def test_timestamp_stale_relative_stale_when_unchanged(skill, metadata, sample_rows, now):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "timestamp_stale", "column": "created_at", "window_mode": "relative"}
    # Max ts in rows is (now - 1hr); snapshot also has (now - 1hr)
    prev_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    result = skill._check_timestamp_stale(
        check, ctx, {"timestamp_values": {"created_at": prev_ts}}, now
    )
    assert result["stale"] is True


def test_timestamp_stale_relative_fresh_when_advanced(skill, metadata, now):
    newer_rows = [
        {"order_id": 1, "created_at": now.strftime("%Y-%m-%d %H:%M:%S"), "status": "active"}
    ]
    meta = QueryMetadata(
        query_id=20, query_name="Q", column_names=["order_id", "created_at", "status"],
        column_types={}, row_count=1, execution_time_ms=10, executed_at=now,
    )
    ctx = make_context(meta, newer_rows, {"checks": [], "channels": []})
    check = {"type": "timestamp_stale", "column": "created_at", "window_mode": "relative"}
    prev_ts = (now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
    result = skill._check_timestamp_stale(
        check, ctx, {"timestamp_values": {"created_at": prev_ts}}, now
    )
    assert result["stale"] is False


def test_timestamp_stale_fixed_stale_when_old(skill, metadata, now):
    old_rows = [
        {"order_id": 1, "created_at": (now - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S"), "status": "x"}
    ]
    meta = QueryMetadata(
        query_id=20, query_name="Q", column_names=["order_id", "created_at", "status"],
        column_types={}, row_count=1, execution_time_ms=10, executed_at=now,
    )
    ctx = make_context(meta, old_rows, {"checks": [], "channels": []})
    check = {"type": "timestamp_stale", "column": "created_at", "window_mode": "fixed", "fixed_hours": 24}
    result = skill._check_timestamp_stale(check, ctx, None, now)
    assert result["stale"] is True
    assert result["age_hours"] > 24


def test_timestamp_stale_missing_column(skill, metadata, sample_rows, now):
    ctx = make_context(metadata, sample_rows, {"checks": [], "channels": []})
    check = {"type": "timestamp_stale", "column": "nonexistent_col", "window_mode": "relative"}
    result = skill._check_timestamp_stale(check, ctx, None, now)
    assert result["stale"] is True
    assert "not found" in result["message"].lower() or "no parseable" in result["message"].lower()


# ---------------------------------------------------------------------------
# Alert mode logic
# ---------------------------------------------------------------------------


def test_should_not_alert_when_fresh(skill):
    result = skill._should_alert(
        cfg={"alert_mode": "on_change"},
        is_stale=False,
        last_snapshot=None,
    )
    assert result is False


def test_should_alert_every_run_when_stale(skill):
    result = skill._should_alert(
        cfg={"alert_mode": "every_run"},
        is_stale=True,
        last_snapshot={"is_stale": True},
    )
    assert result is True


def test_should_alert_on_change_first_time_stale(skill):
    result = skill._should_alert(
        cfg={"alert_mode": "on_change"},
        is_stale=True,
        last_snapshot={"is_stale": False},
    )
    assert result is True


def test_should_not_alert_on_change_already_stale(skill):
    result = skill._should_alert(
        cfg={"alert_mode": "on_change"},
        is_stale=True,
        last_snapshot={"is_stale": True},
    )
    assert result is False


def test_should_alert_on_change_no_prior_snapshot(skill):
    # No baseline — treat previous state as fresh, so stale = transition
    result = skill._should_alert(
        cfg={"alert_mode": "on_change"},
        is_stale=True,
        last_snapshot=None,
    )
    assert result is True


# ---------------------------------------------------------------------------
# check_mode — any vs all
# ---------------------------------------------------------------------------


def test_execute_any_mode_alerts_on_single_failure(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "checks": [
            {"type": "no_rows"},                                    # passes (50 rows)
            {"type": "row_count_unchanged", "window_mode": "relative"},  # fails (same count)
        ],
        "check_mode": "any",
        "alert_mode": "every_run",
        "channels": [{"type": "slack", "webhook_url": "https://hooks.slack.com/x"}],
    })
    with patch.object(skill, "_load_snapshot", return_value={"row_count": 50}), \
         patch.object(skill, "_save_snapshot"), \
         patch.object(skill, "_deliver", return_value=[{"channel": "slack", "success": True, "message": "ok"}]):
        result = skill.execute(ctx)
    assert result.data["alerted"] is True


def test_execute_all_mode_no_alert_on_partial_failure(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "checks": [
            {"type": "no_rows"},                                    # passes (50 rows)
            {"type": "row_count_unchanged", "window_mode": "relative"},  # fails (same count)
        ],
        "check_mode": "all",
        "alert_mode": "every_run",
        "channels": [{"type": "slack", "webhook_url": "https://hooks.slack.com/x"}],
    })
    with patch.object(skill, "_load_snapshot", return_value={"row_count": 50}), \
         patch.object(skill, "_save_snapshot"):
        result = skill.execute(ctx)
    assert result.data["alerted"] is False


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected_none", [
    ("2024-01-15 09:30:00", False),
    ("2024-01-15T09:30:00", False),
    ("2024-01-15T09:30:00Z", False),
    ("2024-01-15T09:30:00.123456+00:00", False),
    ("2024-01-15", False),
    ("not-a-date", True),
    (None, True),
    ("", True),
])
def test_parse_dt(skill, value, expected_none):
    result = skill._parse_dt(value)
    assert (result is None) == expected_none
