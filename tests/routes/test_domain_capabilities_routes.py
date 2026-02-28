from __future__ import annotations

import app.routes.domain_routes as domain_routes


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


def test_domain_capabilities_route_returns_payload(client, monkeypatch):
    class _Svc:
        def get_domain_capabilities(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["domain_id"] == 6
            return {
                "domain_id": 6,
                "domain_version": 1,
                "dimensions": [],
                "domain_metrics": [],
                "user_metrics": [],
                "overlay_metrics": [],
                "time_columns": [],
            }

        def get_overlay_metrics(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["domain_id"] == 6
            return [{"overlay_key": "students_per_teacher", "label": "Students per Teacher", "requires": [6, 5]}]

    monkeypatch.setattr(domain_routes, "DomainCapabilitiesService", _Svc)

    resp_caps = client.get(
        "/api/v1/domains/6/capabilities?vertical_norm=education",
        headers=_headers(monkeypatch),
    )
    assert resp_caps.status_code == 200
    assert resp_caps.json["domain_id"] == 6

    resp_overlay = client.get(
        "/api/v1/domains/6/overlay-metrics?vertical_norm=education",
        headers=_headers(monkeypatch),
    )
    assert resp_overlay.status_code == 200
    assert resp_overlay.json["overlay_metrics"][0]["overlay_key"] == "students_per_teacher"
