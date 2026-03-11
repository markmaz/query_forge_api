from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions.forge_error import ForgeError
from app.models.tenancy_admin import (
    DatasourceCreateRequest,
    OrganizationCreateRequest,
    WorkspaceCreateRequest,
    WorkspaceBindingUpdateRequest,
    WorkspaceMembershipCreateRequest,
)
from app.services.tenancy.tenancy_admin_service import TenancyAdminService


def test_list_organizations_returns_paginated_rows():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "COUNT(*) AS total" in query:
                return [{"total": 1}]
            return [
                {
                    "id": "org-1",
                    "name": "Acme",
                    "slug": "acme",
                    "description": None,
                    "is_active": 1,
                    "created_at": None,
                    "updated_at": None,
                }
            ]

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_organizations()
    assert out["count"] == 1
    assert out["rows"][0]["is_active"] is True


def test_create_organization_conflict_raises_409():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM organization" in query and "WHERE (id = :id OR slug = :slug)" in query:
                return [{"id": "org-1", "slug": "acme"}]
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.create_organization(OrganizationCreateRequest(name="Acme", slug="acme", id="org-1"))
    assert exc.value.status_code == 409


def test_get_organization_serializes_datetime_fields():
    now = datetime(2026, 3, 10, 14, 0, 0)

    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": "org-1",
                        "name": "Acme",
                        "slug": "acme",
                        "description": None,
                        "is_active": 1,
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            return []

    svc = TenancyAdminService(sql=_SQL())
    row = svc.get_organization("org-1")
    assert row["created_at"] == now.isoformat()
    assert row["updated_at"] == now.isoformat()


def test_delete_datasource_soft_sets_inactive():
    class _SQL:
        def __init__(self):
            self.writes = []

        def execute_query_mappings(self, query, params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 9,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, query, params=None):
            self.writes.append((query, params))
            return 1

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.delete_datasource(datasource_id=9, hard=False)
    assert out["deleted"] is True
    assert out["mode"] == "soft"
    assert any("SET is_active = 0" in q for q, _ in sql.writes)


def test_test_datasource_success_updates_status(monkeypatch):
    class _Executor:
        def test_connection(self):
            return None

    class _SQL:
        def __init__(self):
            self.last_params = None

        def execute_query_mappings(self, query, _params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 4,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {"host": "h", "port": 3306, "database": "d", "user": "u", "password": "p"},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, _query, params=None):
            self.last_params = dict(params or {})
            return 1

    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.ExecutorFactory.create", lambda *_args, **_kwargs: _Executor())
    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.test_datasource(datasource_id=4)
    assert out["status"] == "ok"
    assert sql.last_params["last_test_status"] == "ok"


def test_upsert_workspace_membership_missing_workspace_raises_404():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM workspace WHERE id = :id" in query:
                return []
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.upsert_workspace_membership(
            workspace_id="ws-404",
            req=WorkspaceMembershipCreateRequest(user_id="user-1"),
        )
    assert exc.value.status_code == 404


def test_create_datasource_requires_org():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return []
            return []

        def execute_insert(self, *_args, **_kwargs):
            raise AssertionError("should not insert when org is missing")

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.create_datasource(
            organization_id="org-missing",
            req=DatasourceCreateRequest(name="primary", type="snowflake"),
        )
    assert exc.value.status_code == 404


def test_list_workspace_bindings_returns_rows():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "COUNT(*) AS total" in query and "FROM workspace w" in query:
                return [{"total": 1}]
            if "FROM workspace w" in query:
                return [
                    {
                        "workspace_id": "ws-1",
                        "workspace_name": "Main",
                        "workspace_description": None,
                        "workspace_is_active": 1,
                        "default_catalog": "main",
                        "default_schema": "public",
                        "organization_id": "org-1",
                        "organization_name": "Acme",
                        "organization_is_active": 1,
                        "datasource_id": 7,
                        "datasource_name": "Primary",
                        "datasource_slug": "primary",
                        "datasource_type": "mysql",
                        "datasource_is_active": 1,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": "org-1", "name": "Acme", "slug": "acme", "is_active": 1}]
            return []

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_workspace_bindings(organization_id="org-1")
    assert out["count"] == 1
    assert out["rows"][0]["workspace_id"] == "ws-1"
    assert out["rows"][0]["datasource_id"] == 7


def test_update_workspace_binding_rejects_org_datasource_mismatch():
    class _SQL:
        def execute_query_mappings(self, query, params=None):
            if "FROM workspace w" in query and "WHERE w.id = :workspace_id" in query:
                return [
                    {
                        "workspace_id": "ws-1",
                        "workspace_name": "Main",
                        "workspace_description": None,
                        "workspace_is_active": 1,
                        "default_catalog": None,
                        "default_schema": None,
                        "organization_id": "org-1",
                        "organization_name": "Acme",
                        "organization_is_active": 1,
                        "datasource_id": 1,
                        "datasource_name": "Old DS",
                        "datasource_slug": "old-ds",
                        "datasource_type": "mysql",
                        "datasource_is_active": 1,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": params["id"], "name": "Org", "slug": "org", "is_active": 1}]
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": params["id"],
                        "organization_id": "org-2",
                        "name": "DS",
                        "slug": "ds",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.update_workspace_binding(
            workspace_id="ws-1",
            req=WorkspaceBindingUpdateRequest(organization_id="org-1", datasource_id=22),
        )
    assert exc.value.status_code == 400


def test_create_workspace_creates_without_datasource():
    class _SQL:
        def __init__(self):
            self.writes = []

        def execute_query_mappings(self, query, params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": params["id"], "name": "Org", "slug": "org", "is_active": 1}]
            if "SELECT id FROM workspace WHERE id = :id LIMIT 1" in query:
                return []
            if "FROM workspace w" in query and "WHERE w.id = :workspace_id" in query:
                return [
                    {
                        "workspace_id": params["workspace_id"],
                        "workspace_name": "Acme Workspace",
                        "workspace_description": "Primary",
                        "workspace_is_active": 1,
                        "default_catalog": "main",
                        "default_schema": "public",
                        "organization_id": "org-1",
                        "organization_name": "Org",
                        "organization_is_active": 1,
                        "datasource_id": None,
                        "datasource_name": None,
                        "datasource_slug": None,
                        "datasource_type": None,
                        "datasource_is_active": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, query, params=None):
            self.writes.append((query, dict(params or {})))
            return 1

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.create_workspace(
        WorkspaceCreateRequest(
            workspace_id="ws-new-1",
            organization_id="org-1",
            name="Acme Workspace",
            description="Primary",
            default_catalog="main",
            default_schema="public",
        )
    )
    assert out["workspace_id"] == "ws-new-1"
    assert any("INSERT INTO workspace (id) VALUES (:id)" in q for q, _ in sql.writes)


def test_create_workspace_rejects_datasource_org_mismatch():
    class _SQL:
        def execute_query_mappings(self, query, params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": params["id"], "name": "Org", "slug": "org", "is_active": 1}]
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": params["id"],
                        "organization_id": "org-2",
                        "name": "DS",
                        "slug": "ds",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.create_workspace(
            WorkspaceCreateRequest(
                workspace_id="ws-new-2",
                organization_id="org-1",
                datasource_id=44,
            )
        )
    assert exc.value.status_code == 400
