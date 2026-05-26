from __future__ import annotations

import app.features.feedback_learning.analysis_api as analysis_api


def _headers(monkeypatch):
    from flask import g

    from app import factory
    from app.decorators import rbac, security
    from app.routes import request_helpers as _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1"}

    def _allow_workspace_access(*, user_id, workspace_id):
        del user_id
        return workspace_id

    def _ensure_roles_loaded():
        g.effective_roles = {"ai:admin"}

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(_route_utils.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(
        workspace_context.WorkspaceAccessService,
        "assert_workspace_access",
        lambda self, *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(rbac, "workspace_has_feature", lambda workspace_id, feature_key: True)
    monkeypatch.setattr(rbac, "_ensure_roles_loaded", _ensure_roles_loaded)
    monkeypatch.setattr(rbac, "_is_super_admin", lambda: False)
    monkeypatch.setattr(rbac, "_is_workspace_admin", lambda: False)

    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-1",
        "X-User-Id": "user-1",
    }


def test_feedback_learning_analyze_route_returns_analysis_status(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def analyze_feedback(self, prompt_feedback_id: int):
            assert prompt_feedback_id == 41
            return {
                "analysis_id": 55,
                "status": "completed",
                "failure_verdict": "domain_error",
                "candidate_count": 1,
            }

    monkeypatch.setattr(analysis_api, "FailureAnalysisService", _Svc)

    response = client.post(
        "/api/v1/feedback-learning/prompt-feedback/41/analyze",
        headers=_headers(monkeypatch),
    )

    assert response.status_code == 200
    assert response.json == {
        "analysis_id": 55,
        "status": "completed",
        "failure_verdict": "domain_error",
        "candidate_count": 1,
    }


def test_feedback_learning_analyze_route_propagates_not_found(client, monkeypatch):
    from app.exceptions.forge_error import ForgeError

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def analyze_feedback(self, prompt_feedback_id: int):
            raise ForgeError("Prompt feedback not found", status_code=404)

    monkeypatch.setattr(analysis_api, "FailureAnalysisService", _Svc)

    response = client.post(
        "/api/v1/feedback-learning/prompt-feedback/999/analyze",
        headers=_headers(monkeypatch),
    )

    assert response.status_code == 404
    assert response.json["error"] == "Prompt feedback not found"
