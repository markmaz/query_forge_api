from __future__ import annotations

import app.features.query_engine.query_studio_api as query_studio_routes
from app.exceptions.forge_error import ForgeError


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as route_helpers
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    def _allow_workspace_access(*, user_id, workspace_id):
        del user_id
        return workspace_id

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(route_helpers.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(
        workspace_context.WorkspaceAccessService,
        "assert_workspace_access",
        lambda self, *, user_id, workspace_id: workspace_id,
    )
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-1",
        "X-User-Id": "user-1",
    }


def test_query_studio_domains_success(client, monkeypatch):
    class _Svc:
        def list_domains(self, *, workspace_id: str, user_id: str):
            return [
                {
                    "id": 12,
                    "key": "medical_sales",
                    "label": "Medical Sales",
                    "description": "Commercial performance",
                    "fieldCount": 148,
                    "categoryCount": 6,
                    "metricCount": 9,
                }
            ]

    monkeypatch.setattr(query_studio_routes, "QueryStudioDomainExplorerService", _Svc)
    resp = client.get("/api/v1/query-studio/domains", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert isinstance(resp.json, list)
    assert resp.json[0]["key"] == "medical_sales"


def test_query_studio_explorer_success(client, monkeypatch):
    class _Svc:
        def get_domain_explorer(self, *, workspace_id: str, user_id: str, domain_id: int):
            return {
                "domain": {
                    "id": domain_id,
                    "key": "student_outcomes",
                    "label": "Student Outcomes",
                    "fieldCount": 30,
                    "categoryCount": 6,
                    "metricCount": 5,
                    "exampleQuestions": [],
                },
                "recommendedFields": [{"id": 101, "key": "attendance_rate", "label": "Attendance Rate", "path": "attendance.attendance_rate"}],
                "fieldCategories": [
                    {
                        "id": "attendance",
                        "label": "Attendance",
                        "fields": [{"id": 101, "key": "attendance_rate", "label": "Attendance Rate", "path": "attendance.attendance_rate"}],
                    }
                ],
            }

    monkeypatch.setattr(query_studio_routes, "QueryStudioDomainExplorerService", _Svc)
    resp = client.get("/api/v1/query-studio/domains/42/explorer", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json["domain"]["id"] == 42
    assert resp.json["fieldCategories"][0]["label"] == "Attendance"


def test_query_studio_explorer_service_error(client, monkeypatch):
    class _Svc:
        def get_domain_explorer(self, *, workspace_id: str, user_id: str, domain_id: int):
            raise ForgeError("Domain not found", status_code=404)

    monkeypatch.setattr(query_studio_routes, "QueryStudioDomainExplorerService", _Svc)
    resp = client.get("/api/v1/query-studio/domains/999/explorer", headers=_headers(monkeypatch))

    assert resp.status_code == 404
    assert resp.json["error"] == "Domain not found"


def test_query_studio_domains_requires_auth(client):
    resp = client.get("/api/v1/query-studio/domains")
    assert resp.status_code == 403
