from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.workspace_service import WorkspaceService


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
