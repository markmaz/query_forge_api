from __future__ import annotations

import app.routes.planner_extract as planner_extract


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


def test_planner_extract_route_returns_slots(client, monkeypatch):
    class _Svc:
        def extract(self, prompt):
            return {
                "normalized_text": prompt,
                "slots": {"metric": ["chronically absent"], "org_schools": ["Holden Elementary"]},
                "ents": [{"start": 0, "end": 6, "label": "METRIC", "text": "absent"}],
                "by_label": {"METRIC": ["chronically absent"]},
                "warnings": [],
            }

    monkeypatch.setattr(planner_extract, "SemanticExtractService", _Svc)
    resp = client.post(
        "/api/v1/planner/extract",
        json={"prompt": "How many chronically absent students at Holden Elementary this year?"},
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json["slots"]["metric"] == ["chronically absent"]
    assert resp.json["slots"]["org_schools"] == ["Holden Elementary"]
    assert resp.json["by_label"]["METRIC"] == ["chronically absent"]
