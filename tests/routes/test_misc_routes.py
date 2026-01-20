from __future__ import annotations

from typing import Any, Dict, List

import app.routes.connection_routes as connection_routes
import app.routes.functions_routes as functions_routes
import app.routes.product_groups_routes as product_groups_routes
import app.routes.product_routes as product_routes
import app.routes.role_routes as role_routes
import app.routes.workspace_inventory_routes as workspace_inventory_routes
import app.routes.workspace_routes as workspace_routes
import app.routes.workspace_table_routes as workspace_table_routes


class _FakeProductGroup:
    def __init__(self, product_group_id: str) -> None:
        self.product_group_id = product_group_id

    def model_dump(self, mode: str = "json") -> Dict[str, Any]:
        return {"product_group_id": self.product_group_id}


def test_functions_route_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_diag_code_details(self, diag_details: str):
            return {"code": diag_details}

    monkeypatch.setattr(functions_routes, "UdfService", _Svc)

    resp = client.get("/api/v1/functions/diagnosis_code_details/ABC", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["code"] == "ABC"


def test_roles_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_roles(self) -> List[Dict[str, Any]]:
            return [{"role_id": "r1", "role_name": "Admin"}]

    monkeypatch.setattr(role_routes, "RoleService", _Svc)

    resp = client.get("/api/v1/roles", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json[0]["role_id"] == "r1"


def test_products_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_products(self, **kwargs):
            return [], None, None, 0

    monkeypatch.setattr(product_routes, "ProductService", _Svc)

    resp = client.get("/api/v1/products/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["total_count"] == 0


def test_product_groups_get_success(client, monkeypatch):
    class _Svc:
        def get_product_groups(self, status: str = "All"):
            return [_FakeProductGroup("pg-1")]

    monkeypatch.setattr(product_groups_routes, "ProductGroupService", _Svc)

    resp = client.get("/api/v1/product-groups/")
    assert resp.status_code == 200
    assert resp.json[0]["product_group_id"] == "pg-1"


def test_connections_get_by_org_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_connection_by_org(self, organization: str):
            return {"org": organization}

    monkeypatch.setattr(connection_routes, "ConnectionService", _Svc)

    resp = client.get("/api/v1/connections?org=acme", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["org"] == "acme"


def test_workspaces_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_all_workspaces(self):
            return [{"workspace_id": "ws-1"}]

    monkeypatch.setattr(workspace_routes, "WorkspaceService", _Svc)

    resp = client.get("/api/v1/workspaces/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json[0]["workspace_id"] == "ws-1"


def test_workspace_table_columns_success(client, auth_headers, monkeypatch):
    class _FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": 1, "workspace_table_id": 10, "column_name": "c", "data_type": "INT", "ordinal_position": 1}]

    class _FakeConn:
        def execute(self, *args, **kwargs):
            return _FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class _FakeEngine:
        def connect(self):
            return _FakeConn()

    monkeypatch.setattr(workspace_table_routes, "engine", _FakeEngine())

    resp = client.get("/api/v1/workspace-tables/10/columns", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["rows"][0]["column_name"] == "c"


def test_workspace_inventory_unmapped_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_unmapped_tables(self, **kwargs):
            return {"rows": [], "total": 0, "limit": 1, "offset": 0}

    monkeypatch.setattr(workspace_inventory_routes, "UnmappedWorkspaceTablesReadService", _Svc)

    resp = client.get("/api/v1/workspace-inventory/unmapped-tables", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["total"] == 0
