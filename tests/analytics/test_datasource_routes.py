"""Tests for GET /api/v1/datasources — app.routes.datasource_routes."""
from __future__ import annotations

from unittest.mock import MagicMock


import app.routes.datasource_routes as datasource_routes
import app.services.rbac_service as rbac_service
from app.services.analytics.registry import AnalyticsDatasourceRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(datasources: list[dict]) -> AnalyticsDatasourceRegistry:
    """Build a registry whose list_datasources() returns *datasources*."""
    registry = MagicMock(spec=AnalyticsDatasourceRegistry)
    registry.list_datasources.return_value = datasources
    return registry


def _mock_catalog(monkeypatch, datasources: list[dict] | None = None, *, error: Exception | None = None) -> None:
    class _Svc:
        def list_datasources(self, *, include_inactive: bool = False):
            assert include_inactive is False
            if error is not None:
                raise error
            return list(datasources or [])

    monkeypatch.setattr(datasource_routes, "DatasourceCatalogService", _Svc)


def _mock_token(monkeypatch, *, is_admin: bool = True, roles: set[str] | None = None):
    """Patch token verification to always succeed."""
    from app.decorators import security

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": is_admin},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set({"workspace_admin"} if roles is None else roles),
    )


_VALID_HEADERS = {"Authorization": "Bearer test-token", "X-Workspace-Id": "ws-1"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_get_datasources_returns_list(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_catalog(monkeypatch, [])

    registry = _make_registry(
        [
            {"name": "primary", "type": "databricks"},
            {"name": "legacy", "type": "mysql"},
        ]
    )

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get("/api/v1/datasources/", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json
    assert isinstance(data, list)
    names = {item["name"] for item in data}
    assert "primary" in names
    assert "legacy" in names


def test_get_datasources_only_exposes_name_and_type(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_catalog(monkeypatch, [])

    registry = _make_registry([{"name": "primary", "type": "databricks"}])

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get("/api/v1/datasources/", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    item = resp.json[0]
    # Only name and type should be present — no credentials
    assert set(item.keys()) == {"name", "type"}


def test_get_datasources_empty_registry(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_catalog(monkeypatch, [])

    registry = _make_registry([])

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get("/api/v1/datasources/", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json == []


# ---------------------------------------------------------------------------
# Registry unavailable
# ---------------------------------------------------------------------------


def test_get_datasources_returns_503_when_registry_missing(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_catalog(monkeypatch, [])

    # Remove registry from extensions if present
    with client.application.app_context():
        client.application.extensions.pop("analytics_registry", None)

    resp = client.get("/api/v1/datasources/", headers=_VALID_HEADERS)

    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Authentication required
# ---------------------------------------------------------------------------


def test_get_datasources_requires_auth(client):
    resp = client.get("/api/v1/datasources/")
    assert resp.status_code == 403


def test_get_datasources_allows_workspace_admin(client, monkeypatch):
    _mock_token(monkeypatch, is_admin=False, roles={"workspace_admin"})
    _mock_catalog(monkeypatch, [])

    registry = _make_registry([{"name": "primary", "type": "databricks"}])
    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get("/api/v1/datasources/", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json == [{"name": "primary", "type": "databricks"}]


def test_get_datasources_rejects_non_admin_role(client, monkeypatch):
    _mock_token(monkeypatch, is_admin=False, roles={"ingestion:user"})
    _mock_catalog(monkeypatch, [])

    registry = _make_registry([{"name": "primary", "type": "databricks"}])
    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get("/api/v1/datasources/", headers=_VALID_HEADERS)

    assert resp.status_code == 403
    assert "Workspace admin access required." in resp.json["message"]


def test_get_datasources_rejects_invalid_token(client, invalid_auth_headers):
    resp = client.get("/api/v1/datasources/", headers=invalid_auth_headers)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Registry service error
# ---------------------------------------------------------------------------


def test_get_datasources_returns_500_on_registry_error(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_catalog(monkeypatch, error=RuntimeError("unexpected boom"))

    registry = MagicMock(spec=AnalyticsDatasourceRegistry)
    registry.list_datasources.side_effect = RuntimeError("unexpected boom")

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get("/api/v1/datasources/", headers=_VALID_HEADERS)

    assert resp.status_code == 500
