from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services import workspace_service
from app.services.workspace_service import WorkspaceService


class _Resp:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "text"

    def json(self):
        return self._payload


def test_get_all_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.workspace_service.get_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.workspace_service.requests.get", lambda *_args, **_kwargs: _Resp(200))
    monkeypatch.setattr(
        "app.services.workspace_service.process_response",
        lambda _resp: [
            {"workspace_id": "1", "workspace_name": "One", "deployment_name": "https://dbx"},
            {"workspace_id": "2", "workspace_name": "Two", "deployment_name": "https://dbx2"},
        ],
    )
    svc = WorkspaceService()
    workspaces = svc.get_all_workspaces()
    assert workspaces[0]["workspace_id"] == "1"


def test_get_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.workspace_service.get_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.workspace_service.requests.get", lambda *_args, **_kwargs: _Resp(200))
    monkeypatch.setattr(
        "app.services.workspace_service.process_response",
        lambda _resp: {"workspace_id": "1", "workspace_name": "One", "deployment_name": "https://dbx"},
    )
    svc = WorkspaceService()
    ws = svc.get_workspace("1")
    assert ws["workspace_id"] == "1"


def test_get_workspace_users_from_dbx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.workspace_service.get_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        workspace_service.User,
        "to_dict",
        lambda self: {"display_name": self.display_name},
        raising=False,
    )
    monkeypatch.setattr(
        WorkspaceService,
        "get_workspace",
        lambda *_args, **_kwargs: {"server": "https://dbx", "name": "Org"},
    )
    monkeypatch.setattr("app.services.workspace_service.requests.get", lambda *_args, **_kwargs: _Resp(200))
    monkeypatch.setattr(
        "app.services.workspace_service.process_response",
        lambda _resp: {
            "Resources": [
                {"displayName": "Alice", "userName": "alice", "name": {"givenName": "A", "familyName": "B"}}
            ]
        },
    )
    svc = WorkspaceService()
    users = svc.get_workspace_users_from_dbx("1")
    assert users[0]["display_name"] == "A B"


def test_get_workspace_users_from_dbx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ServiceError("missing", 404)

    monkeypatch.setattr(WorkspaceService, "get_workspace", _raise)
    svc = WorkspaceService()
    with pytest.raises(ServiceError):
        svc.get_workspace_users_from_dbx("1")
