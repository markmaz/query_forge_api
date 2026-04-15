"""
tests/test_destinations.py

Tests for WorkspaceDestination model, Fernet encryption helpers,
destination_resolver, and key route behaviours.

Run with: pytest tests/test_destinations.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.models.domain.destinations import (
    DESTINATION_CONFIG_SCHEMAS,
    _count_skills_using_destination,
    decrypt_config,
    encrypt_config,
    mask_config,
    WorkspaceDestination,
)
from app.skills.destination_resolver import resolve_channel_config, validate_destination_ref
from app.skills.delivery import (
    EmailDeliveryChannel,
    GenericWebhookDeliveryChannel,
    SlackDeliveryChannel,
    TeamsDeliveryChannel,
    _ssl_context,
)


def _destination_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    import app.decorators.security as security
    import app.services.rbac_service as rbac_service

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: {"super_admin"},
    )
    monkeypatch.setattr(
        rbac_service,
        "workspace_has_feature",
        lambda workspace_id, feature_key: True,
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fernet_key():
    return Fernet.generate_key().decode()


@pytest.fixture()
def app_with_key(app, fernet_key):
    """Push an app context with the encryption key set."""
    app.config["DESTINATION_ENCRYPTION_KEY"] = fernet_key
    with app.app_context():
        yield app


@pytest.fixture()
def slack_config():
    return {"webhook_url": "https://hooks.slack.com/services/ABC/DEF/xyz"}


@pytest.fixture()
def email_config():
    return {"recipients": ["a@b.com", "c@d.com"], "from_name": "QueryForge", "reply_to": ""}


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip(app_with_key, slack_config):
    encrypted = encrypt_config(slack_config)
    assert isinstance(encrypted, str)
    assert "hooks.slack.com" not in encrypted  # not stored in plaintext
    decrypted = decrypt_config(encrypted)
    assert decrypted == slack_config


def test_encrypt_produces_different_tokens(app_with_key, slack_config):
    # Fernet includes a timestamp — two encryptions of the same data differ
    t1 = encrypt_config(slack_config)
    t2 = encrypt_config(slack_config)
    assert t1 != t2


def test_decrypt_wrong_key_raises(app_with_key, slack_config):
    encrypted = encrypt_config(slack_config)
    # Change the key
    app_with_key.config["DESTINATION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    with pytest.raises(ValueError, match="decrypt"):
        decrypt_config(encrypted)


def test_missing_key_raises(app, slack_config):
    app.config.pop("DESTINATION_ENCRYPTION_KEY", None)
    with app.app_context():
        with pytest.raises(RuntimeError, match="DESTINATION_ENCRYPTION_KEY"):
            encrypt_config(slack_config)


# ---------------------------------------------------------------------------
# Config masking
# ---------------------------------------------------------------------------


def test_mask_slack_config(slack_config):
    masked = mask_config(slack_config, "slack")
    assert masked["webhook_url"] == "••••••"


def test_mask_webhook_config():
    config = {"url": "https://secret.com", "auth_token": "tok123", "method": "POST"}
    masked = mask_config(config, "webhook")
    assert masked["url"] == "••••••"
    assert masked["auth_token"] == "••••••"
    assert masked["method"] == "POST"  # not sensitive


def test_mask_email_group_config(email_config):
    masked = mask_config(email_config, "email_group")
    # No sensitive fields in email_group
    assert masked["recipients"] == email_config["recipients"]
    assert masked["from_name"] == email_config["from_name"]


def test_mask_empty_value_not_replaced():
    config = {"webhook_url": ""}  # empty — don't mask
    masked = mask_config(config, "slack")
    assert masked["webhook_url"] == ""


# ---------------------------------------------------------------------------
# WorkspaceDestination model
# ---------------------------------------------------------------------------


def test_set_and_get_config(app_with_key, slack_config):
    dest = WorkspaceDestination(
        workspace_id=1,
        name="Test Slack",
        destination_type="slack",
        config_json_encrypted="placeholder",
    )
    dest.set_config(slack_config)
    assert dest.get_config() == slack_config


def test_set_config_validates_required_fields(app_with_key):
    dest = WorkspaceDestination(
        workspace_id=1,
        name="Test",
        destination_type="slack",
        config_json_encrypted="placeholder",
    )
    with pytest.raises(ValueError, match="webhook_url"):
        dest.set_config({})  # missing required field


def test_get_masked_config(app_with_key, slack_config):
    dest = WorkspaceDestination(
        workspace_id=1,
        name="Test",
        destination_type="slack",
        config_json_encrypted="placeholder",
    )
    dest.set_config(slack_config)
    masked = dest.get_masked_config()
    assert masked["webhook_url"] == "••••••"


def test_get_masked_config_returns_empty_dict_for_expected_config_errors(app_with_key):
    dest = WorkspaceDestination(
        workspace_id=1,
        name="Test",
        destination_type="slack",
        config_json_encrypted="placeholder",
    )

    with patch.object(dest, "get_config", side_effect=RuntimeError("config unavailable")):
        assert dest.get_masked_config() == {}


def test_get_masked_config_surfaces_unexpected_config_errors(app_with_key):
    dest = WorkspaceDestination(
        workspace_id=1,
        name="Test",
        destination_type="slack",
        config_json_encrypted="placeholder",
    )

    with patch.object(dest, "get_config", side_effect=AssertionError("unexpected config bug")):
        with pytest.raises(AssertionError, match="unexpected config bug"):
            dest.get_masked_config()


def test_to_dict_does_not_expose_plaintext(app_with_key, slack_config):
    dest = WorkspaceDestination(
        workspace_id=1, name="Finance", destination_type="slack",
        config_json_encrypted="placeholder", is_active=True,
        usage_count=0,
    )
    dest.set_config(slack_config)
    d = dest.to_dict()
    assert d["config"]["webhook_url"] == "••••••"
    assert "config_json_encrypted" not in d


def test_get_usage_summary_returns_none_for_expected_usage_lookup_errors(app_with_key):
    dest = WorkspaceDestination(
        id=7,
        workspace_id=1,
        name="Finance",
        destination_type="slack",
        config_json_encrypted="placeholder",
        usage_count=2,
    )

    with patch("app.models.domain.destinations._count_skills_using_destination", side_effect=RuntimeError("db unavailable")):
        summary = dest.get_usage_summary()

    assert summary["usage_count"] == 2
    assert summary["skills_using_count"] is None


def test_get_usage_summary_surfaces_unexpected_usage_lookup_errors(app_with_key):
    dest = WorkspaceDestination(
        id=7,
        workspace_id=1,
        name="Finance",
        destination_type="slack",
        config_json_encrypted="placeholder",
        usage_count=2,
    )

    with patch("app.models.domain.destinations._count_skills_using_destination", side_effect=AssertionError("unexpected usage bug")):
        with pytest.raises(AssertionError, match="unexpected usage bug"):
            dest.get_usage_summary()


# ---------------------------------------------------------------------------
# Destination resolver — backwards compatibility
# ---------------------------------------------------------------------------


def test_resolve_channel_config_passthrough_raw_url():
    """Raw webhook_url configs pass through unchanged (backwards compat)."""
    config = {"type": "slack", "webhook_url": "https://hooks.slack.com/x"}
    result = resolve_channel_config(config, workspace_id=1)
    assert result == config


def test_resolve_channel_config_with_destination_id(app_with_key):
    """destination_id triggers resolver lookup."""
    mock_dest = MagicMock()
    mock_dest.is_active = True
    mock_dest.get_config.return_value = {"webhook_url": "https://hooks.slack.com/real"}
    mock_dest.record_usage = MagicMock()

    config = {"type": "slack", "destination_id": 5}

    with patch("app.skills.destination_resolver.WorkspaceDestination") as MockModel, \
         patch("app.skills.destination_resolver.db"):
        MockModel.query.filter_by.return_value.first.return_value = mock_dest
        result = resolve_channel_config(config, workspace_id=1)

    assert result["webhook_url"] == "https://hooks.slack.com/real"


def test_resolve_channel_config_ignores_expected_usage_record_errors(app_with_key):
    mock_dest = MagicMock()
    mock_dest.is_active = True
    mock_dest.get_config.return_value = {"webhook_url": "https://hooks.slack.com/real"}
    mock_dest.record_usage.side_effect = RuntimeError("usage write unavailable")

    config = {"type": "slack", "destination_id": 5}

    with patch("app.skills.destination_resolver.WorkspaceDestination") as MockModel, \
         patch("app.skills.destination_resolver.db"), \
         patch("app.skills.destination_resolver.logger.warning") as mock_log:
        MockModel.query.filter_by.return_value.first.return_value = mock_dest
        result = resolve_channel_config(config, workspace_id=1)

    assert result["webhook_url"] == "https://hooks.slack.com/real"
    mock_log.assert_called_once()


def test_resolve_channel_config_surfaces_unexpected_usage_record_errors(app_with_key):
    mock_dest = MagicMock()
    mock_dest.is_active = True
    mock_dest.get_config.return_value = {"webhook_url": "https://hooks.slack.com/real"}
    mock_dest.record_usage.side_effect = AssertionError("unexpected usage bug")

    config = {"type": "slack", "destination_id": 5}

    with patch("app.skills.destination_resolver.WorkspaceDestination") as MockModel, \
         patch("app.skills.destination_resolver.db"):
        MockModel.query.filter_by.return_value.first.return_value = mock_dest
        with pytest.raises(AssertionError, match="unexpected usage bug"):
            resolve_channel_config(config, workspace_id=1)


def test_resolve_raises_for_inactive_destination(app_with_key):
    config = {"type": "slack", "destination_id": 99}
    with patch("app.skills.destination_resolver.WorkspaceDestination") as MockModel:
        MockModel.query.filter_by.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found or inactive"):
            resolve_channel_config(config, workspace_id=1)


# ---------------------------------------------------------------------------
# validate_destination_ref
# ---------------------------------------------------------------------------


def test_validate_ref_valid():
    mock_dest = MagicMock(is_active=True)
    with patch("app.skills.destination_resolver.WorkspaceDestination") as MockModel:
        MockModel.query.filter_by.return_value.first.return_value = mock_dest
        errors = validate_destination_ref(1, 1)
    assert errors == []


def test_validate_ref_not_found():
    with patch("app.skills.destination_resolver.WorkspaceDestination") as MockModel:
        MockModel.query.filter_by.return_value.first.return_value = None
        errors = validate_destination_ref(999, 1)
    assert any("not found" in e.lower() for e in errors)


def test_validate_ref_inactive():
    mock_dest = MagicMock(is_active=False, name="Old Channel")
    with patch("app.skills.destination_resolver.WorkspaceDestination") as MockModel:
        MockModel.query.filter_by.return_value.first.return_value = mock_dest
        errors = validate_destination_ref(1, 1)
    assert any("inactive" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Config schemas
# ---------------------------------------------------------------------------


def test_all_types_have_schemas():
    for dtype in ("slack", "teams", "webhook", "email_group"):
        schema = DESTINATION_CONFIG_SCHEMAS[dtype]
        assert "required" in schema
        assert "sensitive" in schema
        assert "properties" in schema


def test_slack_required_fields():
    assert "webhook_url" in DESTINATION_CONFIG_SCHEMAS["slack"]["required"]


def test_email_group_has_no_sensitive_fields():
    assert DESTINATION_CONFIG_SCHEMAS["email_group"]["sensitive"] == []


def test_webhook_marks_url_and_token_sensitive():
    sensitive = DESTINATION_CONFIG_SCHEMAS["webhook"]["sensitive"]
    assert "url" in sensitive
    assert "auth_token" in sensitive


def test_count_skills_using_destination_queries_config_json():
    executed = {}

    class _ScalarResult:
        def scalar(self):
            return 3

    def _fake_execute(query, params):
        executed["query"] = str(query)
        executed["params"] = params
        return _ScalarResult()

    with patch("app.models.domain.destinations.db") as mock_db:
        mock_db.text.side_effect = lambda sql: sql
        mock_db.session.execute.side_effect = _fake_execute
        count = _count_skills_using_destination(17, 9)

    assert count == 3
    assert "JSON_SEARCH(config_json, 'one', :dest_id)" in executed["query"]
    assert executed["params"] == {"ws": 9, "dest_id": "17"}


def test_count_skills_using_destination_returns_zero_for_expected_query_errors():
    with patch("app.models.domain.destinations.db") as mock_db:
        mock_db.session.execute.side_effect = RuntimeError("query unavailable")
        count = _count_skills_using_destination(17, 9)

    assert count == 0


def test_count_skills_using_destination_surfaces_unexpected_query_errors():
    with patch("app.models.domain.destinations.db") as mock_db:
        mock_db.session.execute.side_effect = AssertionError("unexpected query bug")
        with pytest.raises(AssertionError, match="unexpected query bug"):
            _count_skills_using_destination(17, 9)


def test_destination_create_returns_clear_error_when_encryption_key_missing(client, app, monkeypatch):
    app.config["DESTINATION_ENCRYPTION_KEY"] = None

    response = client.post(
        "/api/v1/workspaces/ws-1/destinations/",
        headers=_destination_headers(monkeypatch),
        json={
            "name": "Finance Alerts",
            "destination_type": "slack",
            "config": {"webhook_url": "https://hooks.slack.com/services/ABC/DEF/xyz"},
        },
    )

    assert response.status_code == 503
    assert "DESTINATION_ENCRYPTION_KEY" in response.json["error"]


def test_slack_delivery_uses_certifi_ssl_context():
    channel = SlackDeliveryChannel()
    captured = {}

    class _Response:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, timeout=0, context=None):
        captured["timeout"] = timeout
        captured["context"] = context
        return _Response()

    with patch("app.skills.delivery.urllib_request.urlopen", side_effect=_fake_urlopen):
        success, message = channel.send(
            type(
                "_Payload",
                (),
                {
                    "subject": "Test",
                    "detail_text": "hello",
                    "conditions_failed": [],
                    "query_name": "Test Query",
                    "severity": "info",
                    "workspace_id": 1,
                },
            )(),
            {"webhook_url": "https://hooks.slack.com/services/test"},
        )

    assert success is True
    assert message == "Slack alert delivered."
    assert captured["timeout"] == 10
    assert captured["context"] is not None
    assert captured["context"].get_ca_certs() == _ssl_context().get_ca_certs()


def test_email_delivery_returns_failure_for_expected_runtime_errors():
    channel = EmailDeliveryChannel()
    payload = type(
        "_Payload",
        (),
        {
            "subject": "Test",
            "detail_html": "<p>hello</p>",
            "workspace_id": 1,
        },
    )()

    with patch("app.email.mailer.get_logo", return_value="/tmp/logo.png"), \
         patch("app.email.mailer.send_email", side_effect=RuntimeError("smtp unavailable")):
        success, message = channel.send(payload, {"recipients": ["ops@example.com"]})

    assert success is False
    assert "smtp unavailable" in message


def test_email_delivery_surfaces_unexpected_failures():
    channel = EmailDeliveryChannel()
    payload = type(
        "_Payload",
        (),
        {
            "subject": "Test",
            "detail_html": "<p>hello</p>",
            "workspace_id": 1,
        },
    )()

    with patch("app.email.mailer.get_logo", side_effect=AssertionError("mailer bug")):
        with pytest.raises(AssertionError, match="mailer bug"):
            channel.send(payload, {"recipients": ["ops@example.com"]})


def test_teams_delivery_returns_failure_for_expected_runtime_errors():
    channel = TeamsDeliveryChannel()
    with patch("app.skills.delivery.urllib_request.urlopen", side_effect=RuntimeError("teams offline")):
        success, message = channel.send(
            type(
                "_Payload",
                (),
                {
                    "subject": "Test",
                    "detail_text": "hello",
                    "conditions_failed": [],
                    "query_name": "Test Query",
                    "severity": "info",
                    "workspace_id": 1,
                },
            )(),
            {"webhook_url": "https://outlook.office.com/webhook/test"},
        )

    assert success is False
    assert "teams offline" in message


def test_generic_webhook_delivery_surfaces_unexpected_failures():
    channel = GenericWebhookDeliveryChannel()
    payload = type(
        "_Payload",
        (),
        {
            "subject": "Test",
            "summary": "summary",
            "detail_text": "hello",
            "detail_html": "<p>hello</p>",
            "query_name": "Test Query",
            "workspace_id": 1,
            "query_id": 7,
            "conditions_failed": [],
            "severity": "info",
        },
    )()

    with patch("app.skills.delivery.urllib_request.urlopen", side_effect=AssertionError("webhook bug")):
        with pytest.raises(AssertionError, match="webhook bug"):
            channel.send(payload, {"url": "https://hooks.example.com/test"})
