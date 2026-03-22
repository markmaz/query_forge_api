from __future__ import annotations

import pytest
from flask import g

from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id


def test_extract_workspace_id_missing(app):
    with app.test_request_context("/"):
        with pytest.raises(ForgeError) as exc:
            extract_workspace_id()
    assert exc.value.status_code == 400


def test_extract_workspace_id_checks_membership(app, monkeypatch):
    def _deny_workspace_access(*, user_id: str, workspace_id: str) -> str:
        raise ForgeError("You do not have access to this workspace", status_code=403)

    monkeypatch.setattr(
        "app.routes.request_helpers.workspace_access_service.assert_workspace_access",
        _deny_workspace_access,
    )
    with app.test_request_context("/", headers={"X-Workspace-Id": "ws-2"}):
        g.user_id = "user-1"
        with pytest.raises(ForgeError) as exc:
            extract_workspace_id()
    assert exc.value.status_code == 403


def test_extract_workspace_id_skips_membership_for_super_admin(app, monkeypatch):
    def _deny_workspace_access(*, user_id: str, workspace_id: str) -> str:
        raise AssertionError("membership should not be checked for super_admin")

    monkeypatch.setattr(
        "app.routes.request_helpers.workspace_access_service.assert_workspace_access",
        _deny_workspace_access,
    )
    with app.test_request_context("/", headers={"X-Workspace-Id": "ws-2"}):
        g.user_id = "admin-1"
        g.effective_roles = {"super_admin"}
        assert extract_workspace_id() == "ws-2"
