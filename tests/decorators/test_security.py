from __future__ import annotations

from flask import Flask, g
import pytest

import app.decorators.security as security
import app.services.rbac_service as rbac_service
from app.config import _parse_allowed_origins


def _call_token_required(monkeypatch, get_effective_roles_side_effect):
    app = Flask(__name__)
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: None,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        get_effective_roles_side_effect,
    )

    @security.token_required
    def _secured():
        return {
            "user_id": g.user_id,
            "effective_roles": set(g.effective_roles),
            "is_admin": g.is_admin,
        }

    with app.test_request_context(
        "/secured",
        headers={"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"},
    ):
        return _secured()


def test_token_required_falls_back_when_rbac_runtime_errors(monkeypatch) -> None:
    calls = {"count": 0}

    def _raise_runtime_error(user_id, workspace_id=None):
        calls["count"] += 1
        raise RuntimeError("rbac unavailable")

    payload = _call_token_required(monkeypatch, _raise_runtime_error)

    assert calls["count"] == 2
    assert payload["user_id"] == "user-1"
    assert payload["effective_roles"] == {"super_admin"}
    assert payload["is_admin"] is True


def test_token_required_surfaces_unexpected_preload_errors(monkeypatch) -> None:
    def _raise_assertion_error(user_id, workspace_id=None):
        raise AssertionError("unexpected preload bug")

    with pytest.raises(AssertionError, match="unexpected preload bug"):
        _call_token_required(monkeypatch, _raise_assertion_error)


def test_token_required_surfaces_unexpected_effective_role_load_errors(monkeypatch) -> None:
    responses = iter([None, AssertionError("unexpected effective role bug")])

    def _get_effective_roles(user_id, workspace_id=None):
        result = next(responses)
        if isinstance(result, BaseException):
            raise result
        return result

    with pytest.raises(AssertionError, match="unexpected effective role bug"):
        _call_token_required(monkeypatch, _get_effective_roles)


def test_parse_allowed_origins_supports_csv_and_deduplicates() -> None:
    assert _parse_allowed_origins(
        "https://app.example.com, https://admin.example.com/",
        "https://app.example.com",
        "*",
        " ",
    ) == ("https://app.example.com", "https://admin.example.com")


def test_token_required_options_reflects_allowed_origin() -> None:
    app = Flask(__name__)
    app.config["FRONTEND_ALLOWED_ORIGINS"] = ["https://app.example.com"]

    @security.token_required
    def _secured():
        return {"ok": True}

    with app.test_request_context(
        "/secured",
        method="OPTIONS",
        headers={"Origin": "https://app.example.com"},
    ):
        response, status = _secured()

    assert status == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://app.example.com"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert response.headers["Vary"] == "Origin"


def test_token_required_options_does_not_emit_wildcard_for_disallowed_origin() -> None:
    app = Flask(__name__)
    app.config["FRONTEND_ALLOWED_ORIGINS"] = ["https://app.example.com"]

    @security.token_required
    def _secured():
        return {"ok": True}

    with app.test_request_context(
        "/secured",
        method="OPTIONS",
        headers={"Origin": "https://evil.example.com"},
    ):
        response, status = _secured()

    assert status == 200
    assert "Access-Control-Allow-Origin" not in response.headers
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
