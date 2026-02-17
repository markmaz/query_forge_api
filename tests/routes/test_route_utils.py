from __future__ import annotations

import pytest
from flask import g

from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_workspace_id_from_header


def test_get_workspace_id_from_header_missing(app):
    with app.test_request_context("/"):
        with pytest.raises(ServiceError) as exc:
            get_workspace_id_from_header()
    assert exc.value.status_code == 400


def test_get_workspace_id_from_header_checks_membership(app, monkeypatch):
    def _deny_workspace_access(*, user_id: str, workspace_id: str) -> str:
        raise ServiceError("You do not have access to this workspace", status_code=403)

    monkeypatch.setattr(
        "app.routes._route_utils.workspace_access_service.assert_workspace_access",
        _deny_workspace_access,
    )
    with app.test_request_context("/", headers={"X-Workspace-Id": "ws-2"}):
        g.user_id = "user-1"
        with pytest.raises(ServiceError) as exc:
            get_workspace_id_from_header()
    assert exc.value.status_code == 403
