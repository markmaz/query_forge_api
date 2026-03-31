from __future__ import annotations

from typing import Dict

import app.decorators.security as security
import app.features.workspaces.workspace_feature_api as workspace_feature_routes
import app.services.rbac_service as rbac_service


def _headers(monkeypatch, *, roles: set[str] | None = None) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "admin-1", "username": "admin-1", "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set(roles or {"super_admin"}),
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


class _WorkspaceFeatureRow:
    def __init__(self, feature_key: str) -> None:
        self.feature_key = feature_key


def test_workspace_feature_list_returns_all_keys(client, monkeypatch):
    monkeypatch.setattr(
        workspace_feature_routes,
        "_active_workspace_feature_rows",
        lambda workspace_id: [_WorkspaceFeatureRow("skills"), _WorkspaceFeatureRow("ai")],
    )

    resp = client.get("/api/v1/workspaces/ws-9/features", headers=_headers(monkeypatch, roles={"workspace_admin"}))
    assert resp.status_code == 200
    features = {row["feature_key"]: row["enabled"] for row in resp.json["features"]}
    assert features["skills"] is True
    assert features["ai"] is True
    assert features["forge_match"] is False


def test_workspace_feature_enable_requires_known_feature(client, monkeypatch):
    resp = client.post(
        "/api/v1/workspaces/ws-9/features",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"feature_key": "unknown"},
    )
    assert resp.status_code == 400


def test_workspace_feature_enable_returns_conflict_when_already_enabled(client, monkeypatch):
    monkeypatch.setattr(
        workspace_feature_routes,
        "_feature_row",
        lambda workspace_id, feature_key: object(),
    )

    resp = client.post(
        "/api/v1/workspaces/ws-9/features",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"feature_key": "skills"},
    )
    assert resp.status_code == 409


def test_workspace_feature_enable_success(client, monkeypatch):
    monkeypatch.setattr(workspace_feature_routes, "_feature_row", lambda workspace_id, feature_key: None)
    monkeypatch.setattr(
        workspace_feature_routes,
        "set_workspace_feature",
        lambda **kwargs: {"workspace_id": kwargs["workspace_id"], "feature_key": kwargs["feature_key"], "is_active": True},
    )

    resp = client.post(
        "/api/v1/workspaces/ws-9/features",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"feature_key": "skills"},
    )
    assert resp.status_code == 201
    assert resp.json == {"feature_key": "skills", "enabled": True}


def test_workspace_feature_delete_not_found(client, monkeypatch):
    monkeypatch.setattr(workspace_feature_routes, "_feature_row", lambda workspace_id, feature_key: None)

    resp = client.delete(
        "/api/v1/workspaces/ws-9/features/skills",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
    )
    assert resp.status_code == 404


def test_workspace_feature_delete_success(client, monkeypatch):
    monkeypatch.setattr(workspace_feature_routes, "_feature_row", lambda workspace_id, feature_key: object())
    monkeypatch.setattr(
        workspace_feature_routes,
        "set_workspace_feature",
        lambda **kwargs: {"workspace_id": kwargs["workspace_id"], "feature_key": kwargs["feature_key"], "is_active": False},
    )

    resp = client.delete(
        "/api/v1/workspaces/ws-9/features/skills",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json == {"feature_key": "skills", "enabled": False}


def test_workspace_readiness_success(client, monkeypatch):
    monkeypatch.setattr(
        workspace_feature_routes,
        "_workspace_readiness_payload",
        lambda workspace_id: {
            "workspace_id": workspace_id,
            "workspace_name": "Workspace 9",
            "has_workspace_admin": True,
            "enabled_feature_count": 3,
            "super_user_present": True,
            "setup_complete": True,
            "completed_steps": ["workspace_admin", "workspace_features", "super_user"],
            "missing_steps": [],
        },
    )

    resp = client.get("/api/v1/workspaces/ws-9/readiness", headers=_headers(monkeypatch, roles={"workspace_admin"}))
    assert resp.status_code == 200
    assert resp.json["setup_complete"] is True
