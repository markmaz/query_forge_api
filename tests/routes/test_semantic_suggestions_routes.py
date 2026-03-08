from __future__ import annotations

import app.routes.semantic_suggestions as semantic_suggestions


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as _route_utils
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


def test_items_filtering_endpoint(client, monkeypatch):
    captured = {}

    class _Svc:
        def list_items(self, **kwargs):
            captured.update(kwargs)
            return {"rows": [], "total": 0, "page": kwargs["page"], "page_size": kwargs["page_size"]}

    monkeypatch.setattr(semantic_suggestions, "SemanticSuggestionService", _Svc)

    resp = client.get(
        "/api/v1/semantic/suggestions/items?run_id=5&decision_status=approved&proposed_semantic_type=metric&is_valid=true&page=2&page_size=10",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert captured["run_id"] == 5
    assert captured["decision_status"] == "approved"
    assert captured["proposed_semantic_type"] == "metric"
    assert captured["is_valid"] is True
    assert captured["page"] == 2
    assert captured["page_size"] == 10


def test_patch_item_route_uses_service(client, monkeypatch):
    class _Svc:
        def update_item(self, item_id, payload):
            return {"id": item_id, **payload}

    monkeypatch.setattr(semantic_suggestions, "SemanticSuggestionService", _Svc)

    resp = client.patch(
        "/api/v1/semantic/suggestions/items/9",
        json={"decision_status": "approved", "decision_reason": "looks good"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["item"]["id"] == 9
    assert resp.json["item"]["decision_status"] == "approved"
