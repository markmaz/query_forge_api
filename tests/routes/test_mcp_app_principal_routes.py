from __future__ import annotations

from typing import Dict

import app.decorators.security as security
import app.features.mcp_oauth.app_principal_api as app_principal_api
import app.services.rbac_service as rbac_service


def _headers(monkeypatch, *, roles: set[str] | None = None) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "admin-1", "username": "admin-1", "is_admin": False},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set(roles or {"workspace_admin"}),
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


class _Service:
    def __init__(self) -> None:
        self.created = []
        self.revoked = []

    def list_principals(self, *, workspace_id: str):
        return {
            "workspace_id": workspace_id,
            "items": [
                {
                    "client_id": "qf_app_1",
                    "display_name": "Agent",
                    "description": None,
                    "owning_workspace_id": workspace_id,
                    "owner_user_id": None,
                    "created_by": "admin-1",
                    "created_at": "2026-05-03T10:00:00",
                    "last_used_at": None,
                    "expires_at": None,
                    "revoked_at": None,
                    "rotation_required_at": None,
                    "grant": {
                        "enabled": True,
                        "allowed_tools": ["search_domains"],
                        "allowed_domain_keys": [],
                        "can_preview": False,
                        "preview_row_limit": 100,
                        "expires_at": None,
                        "revoked_at": None,
                        "updated_at": None,
                    },
                }
            ],
        }

    def create_principal(self, *, workspace_id: str, actor_user_id: str, payload):
        self.created.append((workspace_id, actor_user_id, dict(payload)))
        return {
            "workspace_id": workspace_id,
            "client_secret": "qf_app_secret_once",
            "item": {
                "client_id": "qf_app_2",
                "display_name": payload["display_name"],
                "description": None,
                "owning_workspace_id": workspace_id,
                "owner_user_id": None,
                "created_by": actor_user_id,
                "created_at": None,
                "last_used_at": None,
                "expires_at": None,
                "revoked_at": None,
                "rotation_required_at": None,
                "grant": {
                    "enabled": True,
                    "allowed_tools": payload.get("allowed_tools") or [],
                    "allowed_domain_keys": payload.get("allowed_domain_keys") or [],
                    "can_preview": bool(payload.get("can_preview")),
                    "preview_row_limit": int(payload.get("preview_row_limit") or 100),
                    "expires_at": None,
                    "revoked_at": None,
                    "updated_at": None,
                },
            },
        }

    def revoke_principal(self, *, workspace_id: str, client_id: str):
        self.revoked.append((workspace_id, client_id))
        payload = self.list_principals(workspace_id=workspace_id)["items"][0]
        payload["revoked_at"] = "2026-05-03T11:00:00"
        payload["grant"]["enabled"] = False
        return {"workspace_id": workspace_id, "item": payload}


def test_mcp_app_principals_list_requires_workspace_admin(client, monkeypatch):
    service = _Service()
    monkeypatch.setattr(app_principal_api, "_service", lambda: service)

    resp = client.get("/api/v1/workspaces/ws-1/mcp/app-principals", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json["items"][0]["client_id"] == "qf_app_1"
    assert "client_secret" not in resp.json["items"][0]


def test_mcp_app_principals_create_returns_one_time_secret(client, monkeypatch):
    service = _Service()
    monkeypatch.setattr(app_principal_api, "_service", lambda: service)

    resp = client.post(
        "/api/v1/workspaces/ws-1/mcp/app-principals",
        headers=_headers(monkeypatch),
        json={
            "display_name": "District Agent",
            "allowed_tools": ["search_domains"],
            "can_preview": True,
            "preview_row_limit": 25,
        },
    )

    assert resp.status_code == 201
    assert resp.json["client_secret"] == "qf_app_secret_once"
    assert resp.json["item"]["grant"]["can_preview"] is True
    assert service.created[0][0] == "ws-1"
    assert service.created[0][1] == "admin-1"


def test_mcp_app_principals_revoke(client, monkeypatch):
    service = _Service()
    monkeypatch.setattr(app_principal_api, "_service", lambda: service)

    resp = client.delete("/api/v1/workspaces/ws-1/mcp/app-principals/qf_app_1", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json["item"]["grant"]["enabled"] is False
    assert service.revoked == [("ws-1", "qf_app_1")]


def test_mcp_app_principals_rejects_mismatched_workspace_header(client, monkeypatch):
    service = _Service()
    monkeypatch.setattr(app_principal_api, "_service", lambda: service)
    headers = _headers(monkeypatch)
    headers["X-Workspace-Id"] = "ws-other"

    resp = client.get("/api/v1/workspaces/ws-1/mcp/app-principals", headers=headers)

    assert resp.status_code == 400
