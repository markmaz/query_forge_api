from __future__ import annotations

import app.routes.semantic_routes as semantic_routes


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


def test_plan_endpoint_contract_shape(client, monkeypatch):
    class _Svc:
        def plan(self, payload, *, include_llm=True):
            del payload
            base = {
                "prompt": "show students",
                "deterministic": {"matched": [], "unmatched_tokens": []},
                "concept_vector": {"query_text": "show students", "hits": []},
                "concept_mapping": {"concepts": [], "mapped_columns": []},
                "column_vector": {"filtered_to_candidate_count": 0, "hits": []},
                "debug": {"timings_ms": {"deterministic": 0, "concept_vector": 0, "concept_mapping": 0, "column_vector": 0, "llm": 0}, "warnings": []},
            }
            if include_llm:
                base["llm_plan"] = {
                    "model": "qwen2.5-instruct-14b",
                    "sql_json": {"version": 1},
                    "selected_columns": [],
                    "filters": [],
                    "join_plan": {},
                    "confidence": 0.8,
                    "notes": [],
                }
            return base

    monkeypatch.setattr(semantic_routes, "PlanService", _Svc)

    resp = client.post(
        "/api/v1/semantic/plan",
        json={"workspace_id": "ws-1", "vertical_norm": "education", "prompt": "show students"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    body = resp.json
    assert "deterministic" in body
    assert "concept_vector" in body
    assert "concept_mapping" in body
    assert "column_vector" in body
    assert "llm_plan" in body
    assert "debug" in body
