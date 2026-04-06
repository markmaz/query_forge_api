from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def test_base_skill_and_context_importable():
    from app.skills.base import SkillContext

    ctx = SkillContext(workspace_id="ws-1", skill_id="sk-1", execution_id="ex-1")
    assert ctx.workspace_id == "ws-1"
    assert ctx.rows == []
    assert ctx.columns == []


def test_skill_registry_importable():
    from app.skills.registry import SkillRegistry

    assert hasattr(SkillRegistry, "register")
    assert hasattr(SkillRegistry, "get")
    assert hasattr(SkillRegistry, "autodiscover")


def test_email_delivery_skill_type():
    from app.skills.email_delivery import EmailDeliverySkill

    assert EmailDeliverySkill.skill_type == "email_delivery"


def test_email_delivery_registered_after_autodiscover():
    from app.skills.registry import SkillRegistry

    SkillRegistry.autodiscover("app.skills")
    cls = SkillRegistry.get("email_delivery")
    assert cls is not None
    assert cls.skill_type == "email_delivery"


def test_email_delivery_build_html():
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    html = skill._build_html(
        title="Test Report",
        summary="Sales are up.",
        rows=[{"col_a": "v1", "col_b": "v2"}],
        columns=["col_a", "col_b"],
        base_url="http://localhost:3000",
    )
    assert "Test Report" in html
    assert "Sales are up." in html
    assert "col_a" in html
    assert "v1" in html


def _make_context():
    from app.skills.base import QueryMetadata, SkillContext

    return SkillContext(
        workspace_id="ws-1",
        skill_id="sk-1",
        execution_id="ex-1",
        rows=[{"col_a": "v1", "col_b": "v2"}],
        columns=["col_a", "col_b"],
        config={
            "recipients": ["a@example.com", "b@example.com"],
            "subject": "Test Report",
            "include_summary": True,
        },
        metadata=QueryMetadata(
            query_id="q-1",
            query_name="Test Query",
            column_names=["col_a", "col_b"],
            column_types={"col_a": "str", "col_b": "str"},
            row_count=1,
            execution_time_ms=12,
            executed_at=datetime.now(timezone.utc),
        ),
    )


def test_email_delivery_execute_marks_failed_recipient_on_expected_send_error(app):
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    context = _make_context()

    with app.app_context():
        with patch("app.email.mailer.get_logo", return_value="/tmp/logo.png"), \
             patch.object(skill, "_generate_summary", return_value="summary"), \
             patch("app.email.mailer.send_email", side_effect=[None, RuntimeError("smtp unavailable")]):
            result = skill.execute(context)

    assert result["sent"] == 1
    assert result["failed"] == ["b@example.com"]


def test_email_delivery_execute_surfaces_unexpected_send_error(app):
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    context = _make_context()

    with app.app_context():
        with patch("app.email.mailer.get_logo", return_value="/tmp/logo.png"), \
             patch.object(skill, "_generate_summary", return_value="summary"), \
             patch("app.email.mailer.send_email", side_effect=AssertionError("mailer bug")):
            with pytest.raises(AssertionError, match="mailer bug"):
                skill.execute(context)


def test_email_delivery_resolve_destination_returns_empty_on_expected_error():
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    with patch("app.skills.destination_resolver.resolve_channel_config", side_effect=RuntimeError("destination unavailable")):
        assert skill._resolve_destination_config({"destination_id": 7}, "ws-1") == {}


def test_email_delivery_resolve_destination_surfaces_unexpected_error():
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    with patch("app.skills.destination_resolver.resolve_channel_config", side_effect=AssertionError("destination bug")):
        with pytest.raises(AssertionError, match="destination bug"):
            skill._resolve_destination_config({"destination_id": 7}, "ws-1")


def test_email_delivery_generate_summary_returns_empty_on_expected_llm_error():
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    context = _make_context()

    with patch("app.config.llm_resolver.build_llm_client_for_role", side_effect=RuntimeError("llm unavailable")):
        assert skill._generate_summary(context) == ""


def test_email_delivery_generate_summary_surfaces_unexpected_llm_error():
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    context = _make_context()

    with patch("app.config.llm_resolver.build_llm_client_for_role", side_effect=AssertionError("llm bug")):
        with pytest.raises(AssertionError, match="llm bug"):
            skill._generate_summary(context)
