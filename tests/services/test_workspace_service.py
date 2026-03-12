from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.workspace_service import WorkspaceService


class _Resp:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "text"

    def json(self):
        return self._payload


def test_get_all_workspaces_from_db() -> None:
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            assert "FROM workspace w" in query
            return [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "One",
                    "datasource_type": "databricks",
                    "datasource_config_json": {"host": "https://adb-1.azuredatabricks.net"},
                },
                {
                    "workspace_id": "ws-2",
                    "workspace_name": "Two",
                    "datasource_type": "snowflake",
                    "datasource_config_json": {"account": "acme-test"},
                },
            ]

    svc = WorkspaceService(sql=_SQL())
    workspaces = svc.get_all_workspaces()
    assert workspaces[0]["workspace_id"] == "ws-1"
    assert workspaces[0]["server"] == "https://adb-1.azuredatabricks.net"
    assert workspaces[1]["server"] == "https://acme-test.snowflakecomputing.com"


def test_get_workspace_from_db() -> None:
    class _SQL:
        def execute_query_mappings(self, _query, _params=None):
            return [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "One",
                    "datasource_type": "databricks",
                    "datasource_config_json": {"host": "https://adb-1.azuredatabricks.net"},
                }
            ]

    svc = WorkspaceService(sql=_SQL())
    ws = svc.get_workspace("ws-1")
    assert ws["workspace_id"] == "ws-1"
    assert ws["server"] == "https://adb-1.azuredatabricks.net"


def test_get_workspace_missing_raises_404() -> None:
    class _SQL:
        def execute_query_mappings(self, _query, _params=None):
            return []

    svc = WorkspaceService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.get_workspace("missing")
    assert exc.value.status_code == 404


def test_get_workspace_legacy_fallback() -> None:
    class _SQL:
        def __init__(self):
            self.calls = 0

        def execute_query_mappings(self, query, _params=None):
            self.calls += 1
            if "LEFT JOIN datasource d" in query:
                raise RuntimeError("no datasource table")
            assert "w.server AS server" in query
            return [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Legacy",
                    "server": "https://legacy.example.com",
                }
            ]

    svc = WorkspaceService(sql=_SQL())
    ws = svc.get_workspace("ws-1")
    assert ws["workspace_id"] == "ws-1"
    assert ws["server"] == "https://legacy.example.com"


def test_get_workspace_users_from_dbx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.workspace_service.requests.get", lambda *_args, **_kwargs: _Resp(200))
    monkeypatch.setattr(
        "app.services.workspace_service.process_response",
        lambda _resp: {
            "Resources": [
                {"displayName": "Alice", "userName": "alice", "name": {"givenName": "A", "familyName": "B"}}
            ]
        },
    )
    monkeypatch.setattr(
        "app.services.workspace_service.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda self, *, workspace_id, require_active=True: type(
            "Resolved",
            (),
            {
                "datasource_type": "databricks",
                "config_json": {"host": "https://dbx", "token": "dapi-test"},
                "secret_ref": None,
            },
        )(),
    )
    monkeypatch.setattr(
        WorkspaceService,
        "get_workspace",
        lambda *_args, **_kwargs: {"name": "Org"},
    )
    svc = WorkspaceService()
    users = svc.get_workspace_users_from_dbx("1")
    assert users[0]["display_name"] == "A B"


def test_get_workspace_users_from_dbx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ForgeError("missing", 404)

    monkeypatch.setattr(
        "app.services.workspace_service.WorkspaceDatasourceResolverService.resolve_for_workspace",
        _raise,
    )
    svc = WorkspaceService()
    with pytest.raises(ForgeError):
        svc.get_workspace_users_from_dbx("1")

def test_get_workspace_users_from_dbx_non_dbx_datasource_uses_workspace_users() -> None:
    class _SQL:
        def execute_query_mappings(self, query, params=None):
            if "FROM workspace_membership wm" in query and "JOIN users u ON u.user_id = members.user_id" in query:
                return [
                    {
                        "user_id": "u1",
                        "username": "user1",
                        "email": "u1@example.com",
                        "first_name": "U",
                        "last_name": "One",
                        "status": "Active",
                        "is_default": 1,
                        "display_name": "U One",
                    }
                ]
            if "FROM workspace w" in query:
                ws_value = (params or {}).get("workspace_id") or (params or {}).get("ws") or "ws-1"
                return [
                    {
                        "workspace_id": ws_value,
                        "workspace_name": "One",
                        "organization_is_active": 1,
                        "workspace_is_active": 1,
                        "datasource_id": 2,
                        "datasource_name": "sf",
                        "datasource_slug": "sf",
                        "datasource_type": "snowflake",
                        "datasource_is_active": 1,
                        "config_json": {},
                        "secret_ref": None,
                        "default_catalog": None,
                        "default_schema": None,
                        "workspace_organization_id": "org-1",
                        "datasource_organization_id": "org-1",
                    }
                ]
            return []

    svc = WorkspaceService(sql=_SQL())
    users = svc.get_workspace_users_from_dbx("ws-1")
    assert users[0]["user_id"] == "u1"
