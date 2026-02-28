from __future__ import annotations

import app.routes.vector_domains as vector_routes


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    def _allow_workspace_access(*, user_id, workspace_id):
        del user_id
        return workspace_id

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(_route_utils.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
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


def test_vector_domain_search_route_success(client, monkeypatch):
    class _Svc:
        def search_domains(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["vertical_norm"] == "education"
            return {
                "results": [
                    {
                        "domain_id": 7,
                        "name": "Enrollment",
                        "score": 0.71,
                        "reason": ["enrollment", "students"],
                        "domain_version": 3,
                    }
                ]
            }

    monkeypatch.setattr(vector_routes, "DomainVectorIndexService", _Svc)

    resp = client.post(
        "/api/v1/vector/domains/search",
        json={
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "query": "student enrollment",
            "limit": 5,
            "score_threshold": 0.2,
            "include_payload": True,
        },
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json["results"][0]["domain_id"] == 7


def test_vector_domain_search_route_workspace_mismatch(client, monkeypatch):
    resp = client.post(
        "/api/v1/vector/domains/search",
        json={
            "workspace_id": "ws-2",
            "vertical_norm": "education",
            "query": "student enrollment",
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400
