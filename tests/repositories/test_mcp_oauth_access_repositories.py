from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.mcp_oauth import (
    MCPAppClientRepository,
    MCPPrincipalGrantRepository,
    WorkspaceMCPSettingsRepository,
)


class _SQL:
    def __init__(self, rows=None, write_count=1) -> None:
        self.rows = list(rows or [])
        self.queries = []
        self.writes = []
        self.inserts = []
        self.write_count = write_count

    def execute_query_mappings(self, query, params=None):
        self.queries.append((query, dict(params or {})))
        return list(self.rows)

    def execute_write(self, query, params=None):
        self.writes.append((query, dict(params or {})))
        return self.write_count

    def execute_insert(self, query, params=None):
        self.inserts.append((query, dict(params or {})))


def test_workspace_mcp_settings_repository_returns_default_disabled_when_missing():
    repo = WorkspaceMCPSettingsRepository(sql=_SQL(rows=[]))

    settings = repo.get_settings(workspace_id="ws-1")

    assert settings == {
        "workspace_id": "ws-1",
        "enabled": False,
        "default_preview_row_limit": 100,
        "max_preview_row_limit": 500,
        "block_sensitive_domains": False,
    }


def test_workspace_mcp_settings_repository_decodes_boolean_fields():
    sql = _SQL(
        rows=[
            {
                "workspace_id": "ws-1",
                "enabled": 1,
                "default_preview_row_limit": 50,
                "max_preview_row_limit": 250,
                "block_sensitive_domains": 0,
            }
        ]
    )
    repo = WorkspaceMCPSettingsRepository(sql=sql)

    settings = repo.get_settings(workspace_id="ws-1")

    assert settings["enabled"] is True
    assert settings["block_sensitive_domains"] is False
    assert settings["max_preview_row_limit"] == 250


def test_principal_grant_repository_returns_active_grant_and_decodes_json():
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sql = _SQL(
        rows=[
            {
                "principal_type": "app",
                "principal_id": "app-1",
                "workspace_id": "ws-1",
                "enabled": 1,
                "allowed_tools": '["search_domains","plan_query"]',
                "allowed_domain_keys": '["students"]',
                "can_preview": 0,
                "preview_row_limit": 25,
            }
        ]
    )
    repo = MCPPrincipalGrantRepository(sql=sql)

    grant = repo.get_active_grant(
        principal_type="app",
        principal_id="app-1",
        workspace_id="ws-1",
        now=now,
    )

    assert grant is not None
    assert grant["allowed_tools"] == ["search_domains", "plan_query"]
    assert grant["allowed_domain_keys"] == ["students"]
    assert grant["can_preview"] is False
    assert sql.queries[0][1] == {
        "principal_type": "app",
        "principal_id": "app-1",
        "workspace_id": "ws-1",
        "now": now,
    }


def test_app_client_repository_gets_active_client_and_touches_last_used():
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sql = _SQL(
        rows=[
            {
                "client_id": "app-1",
                "client_secret_hash": "hash-1",
                "display_name": "Customer App",
                "owning_workspace_id": "ws-1",
            }
        ],
        write_count=1,
    )
    repo = MCPAppClientRepository(sql=sql)

    row = repo.get_active_client(client_id="app-1", now=now)
    touched = repo.touch_last_used(client_id="app-1", now=now)

    assert row is not None
    assert row["client_id"] == "app-1"
    assert touched is True
    assert "revoked_at IS NULL" in sql.queries[0][0]
    assert "UPDATE mcp_app_clients" in sql.writes[0][0]
