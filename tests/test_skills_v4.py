"""
tests/test_skills_v4.py

Tests for AISummaryDigestSkill and WebhookDeliverySkill.
Run with: pytest tests/test_skills_v4.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.skills.ai_summary_digest import AISummaryDigestSkill
from app.skills.base import QueryMetadata, SkillContext
from app.skills.registry import SkillRegistry
from app.skills.webhook_delivery import WebhookDeliverySkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def digest_skill():
    return AISummaryDigestSkill()


@pytest.fixture()
def webhook_skill():
    return WebhookDeliverySkill()


@pytest.fixture()
def metadata():
    return QueryMetadata(
        query_id=10,
        query_name="Monthly Sales",
        column_names=["month", "revenue", "orders"],
        column_types={"month": "str", "revenue": "float", "orders": "int"},
        row_count=6,
        execution_time_ms=40,
        executed_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def sample_rows():
    return [
        {"month": f"2024-0{i}", "revenue": float(10000 * i), "orders": 50 * i}
        for i in range(1, 7)
    ]


def make_context(metadata, rows, config, workspace_config=None):
    return SkillContext(
        query_id=10,
        workspace_id=3,
        triggered_by="schedule",
        results=rows,
        metadata=metadata,
        config=config,
        workspace_config=workspace_config or {},
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_digest_skill_registered():
    assert SkillRegistry.exists("ai_summary_digest")


def test_webhook_skill_registered():
    assert SkillRegistry.exists("webhook_delivery")


# ---------------------------------------------------------------------------
# AISummaryDigestSkill — validation
# ---------------------------------------------------------------------------


def test_digest_validate_valid(digest_skill):
    errors = digest_skill.validate_config({
        "recipients": ["a@b.com"],
        "subject": "Digest",
    })
    assert errors == []


def test_digest_validate_no_recipients(digest_skill):
    errors = digest_skill.validate_config({"recipients": [], "subject": "Digest"})
    assert any("recipient" in e.lower() for e in errors)


def test_digest_validate_bad_email(digest_skill):
    errors = digest_skill.validate_config({"recipients": ["notanemail"], "subject": "s"})
    assert any("notanemail" in e for e in errors)


def test_digest_validate_empty_subject(digest_skill):
    errors = digest_skill.validate_config({"recipients": ["a@b.com"], "subject": "  "})
    assert any("subject" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# AISummaryDigestSkill — fallback digest (no LLM)
# ---------------------------------------------------------------------------


def test_digest_fallback_when_no_llm(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Test",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={})

    with patch.object(digest_skill, "_send") as mock_send, \
         patch.object(digest_skill, "_load_snapshot", return_value=None), \
         patch.object(digest_skill, "_save_snapshot"):
        result = digest_skill.execute(ctx)

    assert result.success is True
    mock_send.assert_called_once()
    html = mock_send.call_args[0][2]
    assert "Monthly Sales" in html


def test_digest_uses_llm_when_configured(digest_skill, metadata, sample_rows):
    mock_digest = {
        "narrative": "Sales grew steadily across all months.",
        "highlights": ["Revenue up 50%", "Orders doubled"],
        "comparison": None,
    }
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "{{query_name}} Digest",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={"llm": MagicMock()})

    with patch.object(digest_skill, "_generate_digest", return_value=mock_digest), \
         patch.object(digest_skill, "_send") as mock_send, \
         patch.object(digest_skill, "_load_snapshot", return_value=None), \
         patch.object(digest_skill, "_save_snapshot"):
        result = digest_skill.execute(ctx)

    assert result.success is True
    html = mock_send.call_args[0][2]
    assert "Sales grew steadily" in html
    assert "Revenue up 50%" in html


def test_digest_subject_token_rendering(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "{{query_name}} — {{date}}",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    })
    subject = digest_skill._render_subject("{{query_name}} — {{date}}", ctx)
    assert "Monthly Sales" in subject
    assert "{{" not in subject


def test_digest_includes_appendix_when_configured(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
        "include_comparison": False,
        "include_appendix": True,
        "max_rows": 5,
        "include_query_link": False,
    }, workspace_config={})

    with patch.object(digest_skill, "_send") as mock_send, \
         patch.object(digest_skill, "_load_snapshot", return_value=None), \
         patch.object(digest_skill, "_save_snapshot"):
        digest_skill.execute(ctx)

    html = mock_send.call_args[0][2]
    assert "<table" in html
    assert "Raw data" in html


def test_digest_includes_comparison_when_snapshot_exists(digest_skill, metadata, sample_rows):
    snapshot = {
        "highlights": ["Revenue was lower", "Only 3 months"],
        "executed_at": "2024-01-01",
        "row_count": 3,
    }
    mock_digest = {
        "narrative": "Strong growth this period.",
        "highlights": ["Revenue doubled"],
        "comparison": "Revenue increased 100% vs previous run.",
    }
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
        "include_comparison": True,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={"llm": MagicMock()})

    with patch.object(digest_skill, "_generate_digest", return_value=mock_digest), \
         patch.object(digest_skill, "_send") as mock_send, \
         patch.object(digest_skill, "_load_snapshot", return_value=snapshot), \
         patch.object(digest_skill, "_save_snapshot"):
        digest_skill.execute(ctx)

    html = mock_send.call_args[0][2]
    assert "vs previous run" in html
    assert "Revenue increased 100%" in html


# ---------------------------------------------------------------------------
# WebhookDeliverySkill — validation
# ---------------------------------------------------------------------------


def test_webhook_validate_valid(webhook_skill):
    errors = webhook_skill.validate_config({
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
    })
    assert errors == []


def test_webhook_validate_bad_channel(webhook_skill):
    errors = webhook_skill.validate_config({
        "channel_type": "discord",
        "webhook_url": "https://x.com",
        "format": "summary",
    })
    assert any("channel_type" in e.lower() or "slack" in e.lower() for e in errors)


def test_webhook_validate_missing_url(webhook_skill):
    errors = webhook_skill.validate_config({
        "channel_type": "teams",
        "webhook_url": "",
        "format": "summary",
    })
    assert any("webhook" in e.lower() or "url" in e.lower() for e in errors)


def test_webhook_validate_allows_generic_destination(webhook_skill):
    errors = webhook_skill.validate_config({
        "channel_type": "webhook",
        "destination_id": 42,
        "format": "summary",
    })
    assert errors == []


# ---------------------------------------------------------------------------
# WebhookDeliverySkill — execution
# ---------------------------------------------------------------------------


def test_webhook_skips_empty_when_configured(webhook_skill, metadata):
    ctx = make_context(metadata, [], {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
        "send_if_empty": False,
    })
    result = webhook_skill.execute(ctx)
    assert result.success is True
    assert result.data.get("skipped") is True


def test_webhook_sends_when_empty_allowed(webhook_skill, metadata):
    ctx = make_context(metadata, [], {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
        "send_if_empty": True,
    })
    with patch("app.skills.webhook_delivery.get_channel") as mock_get:
        mock_channel = MagicMock()
        mock_channel.send.return_value = (True, "ok")
        mock_get.return_value = mock_channel
        result = webhook_skill.execute(ctx)

    assert result.success is True
    mock_channel.send.assert_called_once()


def test_webhook_slack_summary_format(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
    })
    with patch("app.skills.webhook_delivery.get_channel") as mock_get:
        mock_channel = MagicMock()
        mock_channel.send.return_value = (True, "Slack alert delivered.")
        mock_get.return_value = mock_channel
        result = webhook_skill.execute(ctx)

    assert result.success is True
    payload = mock_channel.send.call_args[0][0]
    assert "Monthly Sales" in payload.detail_text


def test_webhook_table_format(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "teams",
        "webhook_url": "https://outlook.office.com/webhook/x",
        "format": "table",
        "max_rows": 3,
    })
    text = webhook_skill._format_table(ctx, 3)
    assert "```" in text
    assert "month" in text
    assert "revenue" in text


def test_webhook_token_rendering(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://x.com",
        "format": "summary",
        "message": "{{query_name}} has {{row_count}} rows",
    })
    rendered = webhook_skill._render_tokens("{{query_name}} has {{row_count}} rows", ctx)
    assert "Monthly Sales" in rendered
    assert "6" in rendered
    assert "{{" not in rendered


def test_webhook_handles_channel_failure(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
    })
    with patch("app.skills.webhook_delivery.get_channel") as mock_get:
        mock_channel = MagicMock()
        mock_channel.send.return_value = (False, "Connection refused")
        mock_get.return_value = mock_channel
        result = webhook_skill.execute(ctx)

    assert result.success is False
    assert "Connection refused" in result.error


def test_webhook_generic_channel_passes_method_headers_and_token(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "webhook",
        "url": "https://hooks.example.com/queryforge",
        "method": "PUT",
        "headers": {"X-Test": "1"},
        "auth_token": "secret",
        "format": "summary",
    })
    with patch("app.skills.webhook_delivery.get_channel") as mock_get:
        mock_channel = MagicMock()
        mock_channel.send.return_value = (True, "Webhook delivered.")
        mock_get.return_value = mock_channel
        result = webhook_skill.execute(ctx)

    assert result.success is True
    payload_arg, config_arg = mock_channel.send.call_args[0]
    assert payload_arg.query_name == "Monthly Sales"
    assert config_arg == {
        "type": "webhook",
        "url": "https://hooks.example.com/queryforge",
        "method": "PUT",
        "headers": {"X-Test": "1"},
        "auth_token": "secret",
    }


def test_webhook_fans_out_to_all_configured_channels(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "destination_id": 1,
        "format": "summary",
        "channels": [
            {"type": "slack", "destination_id": 1},
            {"type": "email", "destination_id": 23},
        ],
    })

    slack_channel = MagicMock()
    slack_channel.send.return_value = (True, "Slack alert delivered.")
    email_channel = MagicMock()
    email_channel.send.return_value = (True, "Alert emailed to 1 recipient(s).")

    def _get_channel(channel_type: str):
        return {"slack": slack_channel, "email": email_channel}[channel_type]

    with patch("app.skills.webhook_delivery.get_channel", side_effect=_get_channel):
        result = webhook_skill.execute(ctx)

    assert result.success is True
    assert slack_channel.send.call_count == 1
    assert email_channel.send.call_count == 1
    assert result.data["channels"] == [
        {"type": "slack", "success": True, "message": "Slack alert delivered."},
        {"type": "email", "success": True, "message": "Alert emailed to 1 recipient(s)."},
    ]


def test_webhook_execute_returns_failed_result_on_expected_channel_error(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
    })

    with patch("app.skills.webhook_delivery.get_channel", side_effect=RuntimeError("channel unavailable")):
        result = webhook_skill.execute(ctx)

    assert result.success is False
    assert result.message == "Webhook delivery failed."
    assert "channel unavailable" in (result.error or "")


def test_webhook_execute_surfaces_unexpected_channel_errors(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
    })

    with patch("app.skills.webhook_delivery.get_channel", side_effect=AssertionError("channel bug")):
        with pytest.raises(AssertionError, match="channel bug"):
            webhook_skill.execute(ctx)


def test_webhook_build_email_html_returns_empty_on_expected_runtime_error(webhook_skill, metadata, sample_rows, app):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
    })

    with app.app_context():
        with patch("app.skills.email_delivery.EmailDeliverySkill._build_html", side_effect=RuntimeError("html unavailable")):
            assert webhook_skill._build_email_html(ctx, "Subject") == ""


def test_webhook_build_email_html_surfaces_unexpected_errors(webhook_skill, metadata, sample_rows, app):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "summary",
    })

    with app.app_context():
        with patch("app.skills.email_delivery.EmailDeliverySkill._build_html", side_effect=AssertionError("html bug")):
            with pytest.raises(AssertionError, match="html bug"):
                webhook_skill._build_email_html(ctx, "Subject")


def test_webhook_highlights_falls_back_on_expected_llm_error(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "highlights",
    }, workspace_config={"llm": {"provider": "openai"}})

    with patch("app.config.llm_resolver.build_llm_client_for_role", side_effect=RuntimeError("llm unavailable")):
        text = webhook_skill._format_highlights(ctx, ctx.config)

    assert "Monthly Sales" in text


def test_webhook_highlights_surfaces_unexpected_llm_errors(webhook_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "channel_type": "slack",
        "webhook_url": "https://hooks.slack.com/x",
        "format": "highlights",
    }, workspace_config={"llm": {"provider": "openai"}})

    with patch("app.config.llm_resolver.build_llm_client_for_role", side_effect=AssertionError("llm bug")):
        with pytest.raises(AssertionError, match="llm bug"):
            webhook_skill._format_highlights(ctx, ctx.config)


def test_digest_resolves_recipients_from_destination(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "destination_id": 7,
        "subject": "Digest",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={})

    with patch("app.skills.destination_resolver.resolve_channel_config", return_value={"recipients": ["ops@example.com"]}), \
         patch.object(digest_skill, "_send") as mock_send, \
         patch.object(digest_skill, "_load_snapshot", return_value=None), \
         patch.object(digest_skill, "_save_snapshot"):
        result = digest_skill.execute(ctx)

    assert result.success is True
    assert mock_send.call_args[0][0] == ["ops@example.com"]


def test_digest_ignores_expected_destination_resolution_failures(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "destination_id": 7,
        "recipients": ["fallback@example.com"],
        "subject": "Digest",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={})

    with patch("app.skills.destination_resolver.resolve_channel_config", side_effect=RuntimeError("destination unavailable")), \
         patch.object(digest_skill, "_send") as mock_send, \
         patch.object(digest_skill, "_load_snapshot", return_value=None), \
         patch.object(digest_skill, "_save_snapshot"):
        result = digest_skill.execute(ctx)

    assert result.success is True
    assert mock_send.call_args[0][0] == ["fallback@example.com"]


def test_digest_surfaces_unexpected_destination_resolution_failures(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "destination_id": 7,
        "recipients": ["fallback@example.com"],
        "subject": "Digest",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={})

    with patch("app.skills.destination_resolver.resolve_channel_config", side_effect=AssertionError("destination bug")):
        with pytest.raises(AssertionError, match="destination bug"):
            digest_skill.execute(ctx)


def test_digest_generate_digest_falls_back_on_expected_llm_error(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
    }, workspace_config={"llm": {"provider": "openai"}})

    with patch("app.skills.ai_summary_digest.call_analysis_llm", side_effect=RuntimeError("llm unavailable")):
        digest = digest_skill._generate_digest(ctx, ctx.config, None)

    assert "Configure a workspace LLM" in digest["narrative"]


def test_digest_generate_digest_surfaces_unexpected_llm_errors(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
    }, workspace_config={"llm": {"provider": "openai"}})

    with patch("app.skills.ai_summary_digest.call_analysis_llm", side_effect=AssertionError("llm bug")):
        with pytest.raises(AssertionError, match="llm bug"):
            digest_skill._generate_digest(ctx, ctx.config, None)


def test_digest_execute_returns_failed_result_on_expected_send_error(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={})

    with patch.object(digest_skill, "_load_snapshot", return_value=None), \
         patch.object(digest_skill, "_save_snapshot"), \
         patch.object(digest_skill, "_send", side_effect=RuntimeError("smtp unavailable")):
        result = digest_skill.execute(ctx)

    assert result.success is False
    assert result.message == "Email delivery failed."
    assert "smtp unavailable" in (result.error or "")


def test_digest_execute_surfaces_unexpected_send_errors(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
        "include_comparison": False,
        "include_appendix": False,
        "include_query_link": False,
    }, workspace_config={})

    with patch.object(digest_skill, "_load_snapshot", return_value=None), \
         patch.object(digest_skill, "_save_snapshot"), \
         patch.object(digest_skill, "_send", side_effect=AssertionError("mailer bug")):
        with pytest.raises(AssertionError, match="mailer bug"):
            digest_skill.execute(ctx)


def test_digest_load_snapshot_returns_none_on_expected_db_error(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
    })

    class _Query:
        def filter_by(self, **kwargs):
            del kwargs
            raise SQLAlchemyError("db down")

    with patch("app.models.query.skills.QuerySkill.query", _Query()):
        assert digest_skill._load_snapshot(ctx) is None


def test_digest_load_snapshot_surfaces_unexpected_errors(digest_skill, metadata, sample_rows):
    ctx = make_context(metadata, sample_rows, {
        "recipients": ["a@b.com"],
        "subject": "Digest",
    })

    class _Query:
        def filter_by(self, **kwargs):
            del kwargs
            raise AssertionError("snapshot bug")

    with patch("app.models.query.skills.QuerySkill.query", _Query()):
        with pytest.raises(AssertionError, match="snapshot bug"):
            digest_skill._load_snapshot(ctx)
