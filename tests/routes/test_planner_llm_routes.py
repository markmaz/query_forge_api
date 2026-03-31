from __future__ import annotations

import app.features.planner.planner_llm_api as planner_llm_route


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


def test_plan_llm_route_returns_404_when_disabled(client, monkeypatch):
    monkeypatch.setattr(planner_llm_route, "QF_PLANNER_LLM_ENABLED", False)
    resp = client.post(
        "/api/v1/planner/plan_llm",
        json={"workspace_id": "ws-1", "prompt": "students per teacher"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 404


def test_plan_llm_route_returns_service_payload(client, monkeypatch):
    monkeypatch.setattr(planner_llm_route, "QF_PLANNER_LLM_ENABLED", True)

    class _Svc:
        def plan(self, payload):
            assert payload["workspace_id"] == "ws-1"
            return {
                "plan_json": {"intent": "list"},
                "sql_json": {"version": 1},
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "candidates": {"domains": [], "concepts": [], "columns": []},
                "trace_id": "trace-1",
                "timings_ms": {"total": 1},
                "cache": {"hit": False, "key": "k"},
            }

    monkeypatch.setattr(planner_llm_route, "PlannerLLMService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_llm",
        json={"workspace_id": "ws-1", "prompt": "students per teacher", "vertical": "education"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["sql_json"]["version"] == 1
