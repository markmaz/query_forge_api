from __future__ import annotations


def test_admin_healthz_ok(client):
    resp = client.get("/api/v1/admin/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == "OK"


def test_admin_headers_route_is_not_exposed(client):
    resp = client.get("/api/v1/admin/headers/DATABRICKS_TOKEN_MANAGER")
    assert resp.status_code == 404


def test_admin_root_route_is_not_exposed(client):
    resp = client.get("/api/v1/admin/")
    assert resp.status_code == 404
