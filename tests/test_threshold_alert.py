"""
tests/test_threshold_alert.py

Tests for ThresholdAlertSkill, delivery channels, and schedule_utils.
Run with: pytest tests/test_threshold_alert.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from valkey.exceptions import ValkeyError

from app.skills.base import QueryMetadata, SkillContext
from app.skills.delivery import DeliveryPayload, SlackDeliveryChannel, TeamsDeliveryChannel
from app.skills.registry import SkillRegistry
from app.skills.schedule_utils import (
    get_scheduler_health,
    next_n_runs,
    record_dispatch_heartbeat,
    validate_cron,
)
from app.skills.threshold_alert import ThresholdAlertSkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def skill():
    return ThresholdAlertSkill()


@pytest.fixture()
def metadata():
    return QueryMetadata(
        query_id=1,
        query_name="Order Health",
        column_names=["order_id", "status", "total"],
        column_types={"order_id": "int", "status": "str", "total": "float"},
        row_count=10,
        execution_time_ms=50,
        executed_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def sample_rows():
    return [
        {"order_id": i, "status": "active", "total": float(100 * i)}
        for i in range(1, 11)
    ]


def make_context(metadata, rows, config, last_state=None):
    ctx = SkillContext(
        query_id=1,
        workspace_id=5,
        triggered_by="schedule",
        results=rows,
        metadata=metadata,
        config=config,
    )
    return ctx


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_skill_is_registered():
    assert SkillRegistry.exists("threshold_alert")


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_validate_valid_config(skill):
    errors = skill.validate_config({
        "conditions": [{"type": "no_rows"}],
        "channels": [{"type": "slack", "webhook_url": "https://hooks.slack.com/x"}],
    })
    assert errors == []


def test_validate_missing_conditions(skill):
    errors = skill.validate_config({
        "conditions": [],
        "channels": [{"type": "slack", "webhook_url": "https://hooks.slack.com/x"}],
    })
    assert any("condition" in e.lower() for e in errors)


def test_validate_row_count_missing_operator(skill):
    errors = skill.validate_config({
        "conditions": [{"type": "row_count", "value": 100}],
        "channels": [{"type": "slack", "webhook_url": "https://x.com"}],
    })
    assert any("operator" in e.lower() for e in errors)


def test_validate_channel_missing_webhook(skill):
    errors = skill.validate_config({
        "conditions": [{"type": "no_rows"}],
        "channels": [{"type": "slack"}],
    })
    assert any("webhook" in e.lower() for e in errors)


def test_validate_ai_expectation_empty_prompt(skill):
    errors = skill.validate_config({
        "conditions": [{"type": "ai_expectation", "prompt": "  "}],
        "channels": [{"type": "email", "recipients": ["a@b.com"]}],
    })
    assert any("prompt" in e.lower() or "expectation" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Condition evaluators
# ---------------------------------------------------------------------------


def test_eval_no_rows_fails_when_empty(skill, metadata, sample_rows):
    empty_meta = QueryMetadata(**{**metadata.__dict__, "row_count": 0})
    ctx = make_context(empty_meta, [], {"conditions": [{"type": "no_rows"}], "channels": []})
    result = skill._eval_no_rows(ctx)
    assert result["passed"] is False


def test_eval_no_rows_passes_when_rows_exist(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    result = skill._eval_no_rows(ctx)
    assert result["passed"] is True


def test_eval_row_count_fails_when_exceeded(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    result = skill._eval_row_count(ctx, {"type": "row_count", "operator": ">", "value": 5})
    assert result["passed"] is False
    assert result["value"] == 10


def test_eval_row_count_passes_when_under(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    result = skill._eval_row_count(ctx, {"type": "row_count", "operator": ">", "value": 20})
    assert result["passed"] is True


def test_eval_column_change_pct_no_baseline(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    result = skill._eval_column_change_pct(
        ctx,
        {"type": "column_change_pct", "column": "total", "threshold_pct": 10, "aggregate": "sum"},
        last_state={},
    )
    assert result["passed"] is True
    assert result["prev_value"] is None


def test_eval_column_change_pct_within_threshold(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    result = skill._eval_column_change_pct(
        ctx,
        {"type": "column_change_pct", "column": "total", "threshold_pct": 50, "aggregate": "sum"},
        last_state={"column_values": {"total:sum": 5400.0}},  # ~0.0% change from 5500
    )
    assert result["passed"] is True


def test_eval_column_change_pct_exceeds_threshold(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    result = skill._eval_column_change_pct(
        ctx,
        {"type": "column_change_pct", "column": "total", "threshold_pct": 5, "aggregate": "sum"},
        last_state={"column_values": {"total:sum": 1000.0}},  # big change from 5500
    )
    assert result["passed"] is False
    assert result["change_pct"] > 5


# ---------------------------------------------------------------------------
# Alert mode logic
# ---------------------------------------------------------------------------


def test_should_not_alert_when_all_passed(skill):
    result = skill._should_alert(
        cfg={"alert_mode": "every_run"},
        all_passed=True,
        conditions_failed=[],
        last_state={},
        context=MagicMock(),
    )
    assert result is False


def test_should_alert_every_run_when_failed(skill):
    result = skill._should_alert(
        cfg={"alert_mode": "every_run"},
        all_passed=False,
        conditions_failed=[{"type": "no_rows", "message": "no rows"}],
        last_state={},
        context=MagicMock(),
    )
    assert result is True


def test_should_alert_on_change_first_failure(skill):
    # was_passing=True (default), now failing → should alert
    result = skill._should_alert(
        cfg={"alert_mode": "on_change", "resolution_mode": "auto"},
        all_passed=False,
        conditions_failed=[{"type": "no_rows", "message": "no rows"}],
        last_state={"all_passed": True},
        context=MagicMock(),
    )
    assert result is True


def test_should_not_alert_on_change_repeated_failure(skill):
    # was already failing → don't re-alert
    result = skill._should_alert(
        cfg={"alert_mode": "on_change", "resolution_mode": "auto"},
        all_passed=False,
        conditions_failed=[{"type": "no_rows", "message": "no rows"}],
        last_state={"all_passed": False},
        context=MagicMock(),
    )
    assert result is False


# ---------------------------------------------------------------------------
# Aggregation helper
# ---------------------------------------------------------------------------


def test_aggregate_sum(skill, sample_rows):
    result = skill._aggregate_column(sample_rows, "total", "sum")
    assert result == sum(float(100 * i) for i in range(1, 11))


def test_aggregate_avg(skill, sample_rows):
    result = skill._aggregate_column(sample_rows, "total", "avg")
    assert result == pytest.approx(550.0)


def test_aggregate_missing_column(skill, sample_rows):
    result = skill._aggregate_column(sample_rows, "nonexistent", "sum")
    assert result is None


# ---------------------------------------------------------------------------
# Delivery channels
# ---------------------------------------------------------------------------


def test_slack_channel_missing_webhook():
    ch = SlackDeliveryChannel()
    payload = DeliveryPayload(
        subject="Test", summary="Test", detail_html="", detail_text="Test",
        query_name="Q", workspace_id=1, query_id=1, conditions_failed=[],
    )
    success, msg = ch.send(payload, {})
    assert success is False
    assert "webhook" in msg.lower()


def test_teams_channel_missing_webhook():
    ch = TeamsDeliveryChannel()
    payload = DeliveryPayload(
        subject="Test", summary="Test", detail_html="", detail_text="Test",
        query_name="Q", workspace_id=1, query_id=1, conditions_failed=[],
    )
    success, msg = ch.send(payload, {})
    assert success is False
    assert "webhook" in msg.lower()


def test_slack_channel_posts_to_webhook():
    ch = SlackDeliveryChannel()
    payload = DeliveryPayload(
        subject="Alert", summary="Row count too high", detail_html="", detail_text="Row count too high",
        query_name="Orders", workspace_id=1, query_id=1,
        conditions_failed=[{"type": "row_count", "message": "row count is 600"}],
    )
    with patch.object(ch, "_post_webhook", return_value=(True, "ok")) as mock_post:
        success, msg = ch.send(payload, {"webhook_url": "https://hooks.slack.com/x"})
    assert success is True
    mock_post.assert_called_once()
    body = mock_post.call_args[0][1]
    assert "blocks" in body


def test_slack_channel_resolves_destination_using_payload_workspace_id():
    ch = SlackDeliveryChannel()
    payload = DeliveryPayload(
        subject="Alert",
        summary="Row count too high",
        detail_html="",
        detail_text="Row count too high",
        query_name="Orders",
        workspace_id=42,
        query_id=1,
        conditions_failed=[],
    )
    with patch("app.skills.destination_resolver.resolve_channel_config", return_value={"webhook_url": "https://hooks.slack.com/x"}) as mock_resolve, \
         patch.object(ch, "_post_webhook", return_value=(True, "ok")) as mock_post:
        success, msg = ch.send(payload, {"destination_id": 7})

    assert success is True
    assert msg == "ok"
    mock_resolve.assert_called_once_with({"destination_id": 7}, 42)
    mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# Schedule utilities
# ---------------------------------------------------------------------------


def test_validate_cron_valid():
    errors = validate_cron("0 9 * * 1-5", "UTC")
    assert errors == []


def test_validate_cron_invalid_expression():
    errors = validate_cron("not a cron", "UTC")
    assert any("invalid" in e.lower() for e in errors)


def test_validate_cron_too_frequent():
    errors = validate_cron("* * * * *", "UTC")  # every minute
    assert any("minimum" in e.lower() or "interval" in e.lower() for e in errors)


def test_validate_cron_five_minutes_ok():
    errors = validate_cron("*/5 * * * *", "UTC")  # every 5 minutes — exactly at limit
    assert errors == []


def test_validate_cron_bad_timezone():
    errors = validate_cron("0 9 * * *", "Not/ATimezone")
    assert any("timezone" in e.lower() for e in errors)


def test_next_n_runs_returns_correct_count():
    runs = next_n_runs("0 9 * * 1-5", "UTC", n=5)
    assert len(runs) == 5


def test_next_n_runs_invalid_expression():
    runs = next_n_runs("not valid", "UTC", n=5)
    assert runs == []


def test_next_n_runs_are_in_future():
    from datetime import datetime, timezone
    runs = next_n_runs("0 9 * * *", "UTC", n=3)
    now = datetime.now(timezone.utc).isoformat()
    for run in runs:
        assert run > now


def test_validate_cron_returns_error_on_expected_runtime_failure():
    class _BrokenCroniter:
        @staticmethod
        def is_valid(expression):
            return True

        def __init__(self, expression, base):
            raise RuntimeError("cron runtime unavailable")

    with patch("app.skills.schedule_utils.croniter", _BrokenCroniter):
        errors = validate_cron("0 9 * * *", "UTC")

    assert any("could not evaluate cron interval" in error.lower() for error in errors)


def test_validate_cron_surfaces_unexpected_runtime_failure():
    class _BrokenCroniter:
        @staticmethod
        def is_valid(expression):
            return True

        def __init__(self, expression, base):
            raise AssertionError("cron bug")

    with patch("app.skills.schedule_utils.croniter", _BrokenCroniter):
        with pytest.raises(AssertionError, match="cron bug"):
            validate_cron("0 9 * * *", "UTC")


def test_next_n_runs_returns_empty_on_expected_runtime_failure():
    with patch("app.skills.schedule_utils.pytz.timezone", side_effect=RuntimeError("timezone unavailable")):
        assert next_n_runs("0 9 * * *", "UTC", n=2) == []


def test_next_n_runs_surfaces_unexpected_runtime_failure():
    with patch("app.skills.schedule_utils.pytz.timezone", side_effect=AssertionError("timezone bug")):
        with pytest.raises(AssertionError, match="timezone bug"):
            next_n_runs("0 9 * * *", "UTC", n=2)


def test_get_scheduler_health_returns_error_payload_on_expected_valkey_failure():
    with patch("app.skills.schedule_utils._valkey_client", side_effect=ValkeyError("valkey unavailable")):
        result = get_scheduler_health()

    assert result["healthy"] is False
    assert "valkey unavailable" in result["reason"]


def test_get_scheduler_health_surfaces_unexpected_failures():
    with patch("app.skills.schedule_utils._valkey_client", side_effect=AssertionError("health bug")):
        with pytest.raises(AssertionError, match="health bug"):
            get_scheduler_health()


def test_record_dispatch_heartbeat_ignores_expected_valkey_failure():
    fake_client = MagicMock()
    fake_client.setex.side_effect = ValkeyError("valkey unavailable")

    with patch("app.skills.schedule_utils._valkey_client", return_value=fake_client):
        record_dispatch_heartbeat()


def test_record_dispatch_heartbeat_surfaces_unexpected_failures():
    fake_client = MagicMock()
    fake_client.setex.side_effect = AssertionError("heartbeat bug")

    with patch("app.skills.schedule_utils._valkey_client", return_value=fake_client):
        with pytest.raises(AssertionError, match="heartbeat bug"):
            record_dispatch_heartbeat()


def test_ai_expectation_fail_open_on_expected_runtime_error(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})

    with patch("app.tasks.skill_runner._get_workspace_config", return_value={"llm": {"provider": "openai"}}), \
         patch.object(skill, "_call_llm_for_verdict", side_effect=RuntimeError("llm unavailable")):
        result = skill._eval_ai_expectation(ctx, {"type": "ai_expectation", "prompt": "Rows should be valid"})

    assert result["passed"] is True
    assert "unavailable" in result["message"]


def test_ai_expectation_surfaces_unexpected_failures(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})

    with patch("app.tasks.skill_runner._get_workspace_config", return_value={"llm": {"provider": "openai"}}), \
         patch.object(skill, "_call_llm_for_verdict", side_effect=AssertionError("bad llm state")):
        with pytest.raises(AssertionError, match="bad llm state"):
            skill._eval_ai_expectation(ctx, {"type": "ai_expectation", "prompt": "Rows should be valid"})


def test_load_last_state_returns_empty_on_expected_runtime_error(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    fake_sql = MagicMock()
    fake_sql.execute_query_mappings.side_effect = RuntimeError("db unavailable")

    with patch("app.adapters.mysql_sql_executor.ForgeMetaSQL", return_value=fake_sql):
        assert skill._load_last_state(ctx) == {}


def test_load_last_state_surfaces_unexpected_failures(skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {"conditions": [], "channels": []})
    fake_sql = MagicMock()
    fake_sql.execute_query_mappings.side_effect = AssertionError("bad db state")

    with patch("app.adapters.mysql_sql_executor.ForgeMetaSQL", return_value=fake_sql):
        with pytest.raises(AssertionError, match="bad db state"):
            skill._load_last_state(ctx)


def test_deliver_converts_expected_channel_failures_to_results(skill):
    payload = DeliveryPayload(
        subject="Alert",
        summary="Alert",
        detail_html="",
        detail_text="Alert",
        query_name="Orders",
        workspace_id=1,
        query_id=1,
        conditions_failed=[],
    )
    fake_channel = MagicMock()
    fake_channel.send.side_effect = RuntimeError("slack offline")

    with patch("app.skills.threshold_alert.get_channel", return_value=fake_channel):
        result = skill._deliver(payload, [{"type": "slack", "webhook_url": "https://hooks.slack.com/x"}])

    assert result == [{"channel": "slack", "success": False, "message": "slack offline"}]


def test_deliver_surfaces_unexpected_channel_failures(skill):
    payload = DeliveryPayload(
        subject="Alert",
        summary="Alert",
        detail_html="",
        detail_text="Alert",
        query_name="Orders",
        workspace_id=1,
        query_id=1,
        conditions_failed=[],
    )
    fake_channel = MagicMock()
    fake_channel.send.side_effect = AssertionError("programmer bug")

    with patch("app.skills.threshold_alert.get_channel", return_value=fake_channel):
        with pytest.raises(AssertionError, match="programmer bug"):
            skill._deliver(payload, [{"type": "slack", "webhook_url": "https://hooks.slack.com/x"}])
