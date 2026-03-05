from __future__ import annotations

import app.routes.planner_domain as planner_domain_route
from app.exceptions.service_error import ServiceError


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


def test_plan_domain_route_returns_service_payload(client, monkeypatch):
    class _Svc:
        def plan(self, payload, *, user_id):
            assert payload["workspace_id"] == "ws-1"
            assert user_id == "user-1"
            return {
                "plan_json_v2": {"schema_version": 2},
                "sql_json": {"version": 1},
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "trace_id": "trace-1",
                "timings_ms": {"total": 1},
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_domain",
        json={"workspace_id": "ws-1", "prompt": "students per teacher by county", "vertical_norm": "education"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["plan_json_v2"]["schema_version"] == 2


def test_plan_domain_route_workspace_mismatch(client, monkeypatch):
    resp = client.post(
        "/api/v1/planner/plan_domain",
        json={"workspace_id": "ws-other", "prompt": "students by county"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400


def test_plan_domain_route_passes_conversation_id(client, monkeypatch):
    class _Svc:
        def plan(self, payload, *, user_id):
            assert payload["conversation_id"] == "pdc_abc123"
            assert user_id == "user-1"
            return {
                "plan_json_v2": {"schema_version": 2},
                "sql_json": {"version": 1},
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "trace_id": "trace-1",
                "conversation_id": "pdc_abc123",
                "timings_ms": {"total": 1},
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_domain",
        json={"workspace_id": "ws-1", "prompt": "sort by position", "conversation_id": "pdc_abc123"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["conversation_id"] == "pdc_abc123"


def test_plan_domain_route_passes_seed_context_fields(client, monkeypatch):
    class _Svc:
        def plan(self, payload, *, user_id):
            assert payload["conversation_id"] == "pdc_abc123"
            assert isinstance(payload["context_seed_plan_json_v2"], dict)
            assert payload["context_seed_last_prompt"] == "show me the staff at barksdale elementary"
            assert user_id == "user-1"
            return {
                "plan_json_v2": {"schema_version": 2},
                "sql_json": {"version": 1},
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "trace_id": "trace-1",
                "conversation_id": "pdc_abc123",
                "timings_ms": {"total": 1},
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_domain",
        json={
            "workspace_id": "ws-1",
            "prompt": "sort by position",
            "conversation_id": "pdc_abc123",
            "context_seed_plan_json_v2": {"schema_version": 2, "base_domain_id": 5},
            "context_seed_last_prompt": "show me the staff at barksdale elementary",
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200


def test_plan_domain_profile_route_returns_service_payload(client, monkeypatch):
    class _Svc:
        def get_pipeline_profile(self, *, trace_id, workspace_id, user_id):
            assert trace_id == "trace-123"
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            return {
                "trace_id": "trace-123",
                "workspace_id": "ws-1",
                "user_id": "user-1",
                "total_ms": 812,
                "steps": [{"index": 1, "label": "Domain selection", "ms": 25}],
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.get(
        "/api/v1/planner/plan_domain/profile/trace-123",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["trace_id"] == "trace-123"
    assert resp.json["total_ms"] == 812


def test_plan_domain_profile_route_not_found(client, monkeypatch):
    class _Svc:
        def get_pipeline_profile(self, *, trace_id, workspace_id, user_id):
            del workspace_id, user_id
            raise ServiceError("Pipeline profile not found", status_code=404, details={"trace_id": trace_id})

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.get(
        "/api/v1/planner/plan_domain/profile/missing-trace",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 404
    assert resp.json["error"] == "Pipeline profile not found"


def test_plan_domain_next_actions_route_returns_service_payload(client, monkeypatch):
    class _Svc:
        def generate_next_actions(self, payload, *, user_id):
            assert payload["workspace_id"] == "ws-1"
            assert user_id == "user-1"
            assert payload["prompt"] == "show follow ups"
            return {
                "next_actions": [{"label": "A", "prompt": "B", "reason": "C", "intent": "list"}],
                "next_actions_status": "ready",
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_domain/next_actions",
        json={"workspace_id": "ws-1", "prompt": "show follow ups", "plan_json_v2": {"base_domain_id": 5}},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["next_actions_status"] == "ready"
