from __future__ import annotations

from app.exceptions.forge_error import ForgeError
from app.services.mcp_oauth.app_principal_service import MCPAppPrincipalService


class _Clients:
    def __init__(self) -> None:
        self.created = []
        self.revoked = []
        self.rows = []

    def list_workspace_clients(self, *, workspace_id: str):
        return list(self.rows)

    def create_client(self, *, payload):
        self.created.append(dict(payload))
        self.rows.append(
            {
                **payload,
                "created_at": "2026-05-03 10:00:00",
                "last_used_at": None,
                "revoked_at": None,
                "rotation_required_at": None,
            }
        )

    def get_client(self, *, client_id: str, workspace_id: str):
        for row in self.rows:
            if row["client_id"] == client_id and row["owning_workspace_id"] == workspace_id:
                return dict(row)
        return None

    def revoke_client(self, *, client_id: str, workspace_id: str):
        self.revoked.append((client_id, workspace_id))
        for row in self.rows:
            if row["client_id"] == client_id and row["owning_workspace_id"] == workspace_id:
                row["revoked_at"] = "2026-05-03 11:00:00"
                return True
        return False


class _Grants:
    def __init__(self) -> None:
        self.rows = {}
        self.revoked = []

    def upsert_app_grant(self, **kwargs):
        row = {
            "enabled": kwargs["enabled"],
            "allowed_tools": kwargs["allowed_tools"] or [],
            "allowed_domain_keys": kwargs["allowed_domain_keys"] or [],
            "can_preview": kwargs["can_preview"],
            "preview_row_limit": kwargs["preview_row_limit"],
            "expires_at": kwargs["expires_at"],
            "revoked_at": None,
            "updated_at": "2026-05-03 10:00:00",
        }
        self.rows[(kwargs["principal_id"], kwargs["workspace_id"])] = row
        return dict(row)

    def get_app_grant(self, *, principal_id: str, workspace_id: str):
        return dict(self.rows.get((principal_id, workspace_id), {}))

    def revoke_app_grant(self, *, principal_id: str, workspace_id: str):
        self.revoked.append((principal_id, workspace_id))
        row = self.rows.get((principal_id, workspace_id))
        if row:
            row["enabled"] = False
            row["revoked_at"] = "2026-05-03 11:00:00"
        return bool(row)


def test_app_principal_service_creates_hashed_client_and_grant():
    clients = _Clients()
    grants = _Grants()
    service = MCPAppPrincipalService(clients=clients, grants=grants)

    result = service.create_principal(
        workspace_id="ws-1",
        actor_user_id="admin-1",
        payload={
            "display_name": "District Agent",
            "description": "Nightly MCP access",
            "allowed_tools": ["search_domains", "plan_query"],
            "allowed_domain_keys": ["attendance"],
            "can_preview": True,
            "preview_row_limit": 50,
        },
    )

    assert result["client_secret"].startswith("qf_app_secret_")
    assert result["item"]["client_id"].startswith("qf_app_")
    assert clients.created[0]["client_secret_hash"] != result["client_secret"]
    assert clients.created[0]["display_name"] == "District Agent"
    assert result["item"]["grant"]["allowed_tools"] == ["search_domains", "plan_query"]
    assert result["item"]["grant"]["can_preview"] is True
    assert result["item"]["grant"]["preview_row_limit"] == 50


def test_app_principal_service_rejects_unknown_tool():
    service = MCPAppPrincipalService(clients=_Clients(), grants=_Grants())

    try:
        service.create_principal(
            workspace_id="ws-1",
            actor_user_id="admin-1",
            payload={"display_name": "Bad Agent", "allowed_tools": ["drop_database"]},
        )
    except ForgeError as exc:
        assert exc.status_code == 400
        assert exc.details == {"unsupported_tools": ["drop_database"]}
    else:
        raise AssertionError("Expected ForgeError")


def test_app_principal_service_revokes_client_and_grant():
    clients = _Clients()
    grants = _Grants()
    service = MCPAppPrincipalService(clients=clients, grants=grants)
    created = service.create_principal(
        workspace_id="ws-1",
        actor_user_id="admin-1",
        payload={"display_name": "Agent"},
    )

    result = service.revoke_principal(workspace_id="ws-1", client_id=created["item"]["client_id"])

    assert clients.revoked == [(created["item"]["client_id"], "ws-1")]
    assert grants.revoked == [(created["item"]["client_id"], "ws-1")]
    assert result["item"]["revoked_at"] == "2026-05-03 11:00:00"
    assert result["item"]["grant"]["enabled"] is False
