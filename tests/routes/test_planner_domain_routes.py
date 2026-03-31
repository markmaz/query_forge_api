from __future__ import annotations

import json
from pathlib import Path

import app.features.planner.planner_domain_api as planner_domain_route
from app.exceptions.forge_error import ForgeError


_GOLDEN_DIR = Path(__file__).resolve().parent.parent / "services" / "planner_domain" / "golden"


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


def _load_golden_debug(name: str) -> dict:
    return json.loads((_GOLDEN_DIR / f"{name}.json").read_text())


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


def test_plan_domain_route_calendar_days_off_workflow_payload_survives_http_boundary(client, monkeypatch):
    prompt = "Show me all the days off barksdale elementary has in December"
    golden_debug = _load_golden_debug("calendar_days_off")

    class _Svc:
        def plan(self, payload, *, user_id):
            assert payload["prompt"] == prompt
            assert payload["vertical_norm"] == "education"
            assert payload["workspace_id"] == "ws-1"
            assert user_id == "user-1"
            return {
                "plan_json_v2": {
                    "schema_version": 2,
                    "base_domain_id": 6,
                    "domain_name": "Academic Calendar And Scheduling",
                },
                "sql_json": {
                    "version": 1,
                    "domainId": 6,
                    "filters": {
                        "type": "group",
                        "match": "and",
                        "children": [
                            {"op": "equals", "value": "Barksdale Elementary"},
                            {"op": "equals", "value": False},
                            {"op": "between", "value": ["2025-12-01", "2025-12-31"]},
                        ],
                    },
                    "meta": {"prompt": prompt},
                },
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "debug": golden_debug,
                "trace_id": "trace-calendar",
                "timings_ms": {"total": 10},
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_domain",
        json={"workspace_id": "ws-1", "prompt": prompt, "vertical_norm": "education", "debug": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["plan_json_v2"]["base_domain_id"] == 6
    assert "calendar_days_off_prompt" in resp.json["debug"]["rerank_signals"]
    assert resp.json["sql_json"]["filters"]["children"][2]["value"] == ["2025-12-01", "2025-12-31"]


def test_plan_domain_route_age_extreme_workflow_payload_survives_http_boundary(client, monkeypatch):
    prompt = "Show me the eldest student"
    golden_debug = _load_golden_debug("age_extreme")

    class _Svc:
        def plan(self, payload, *, user_id):
            assert payload["prompt"] == prompt
            assert payload["workspace_id"] == "ws-1"
            assert user_id == "user-1"
            return {
                "plan_json_v2": {
                    "schema_version": 2,
                    "base_domain_id": 21,
                    "domain_name": "Student Demographics And Enrollment",
                    "grouping": {"limit": 1, "order_by": [{"by": "wt24.birth_date", "dir": "asc"}]},
                },
                "sql_json": {
                    "version": 1,
                    "domainId": 21,
                    "sorting": [{"col": {"columnName": "birth_date"}, "dir": "asc"}],
                    "meta": {"prompt": prompt},
                },
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "debug": golden_debug,
                "trace_id": "trace-age",
                "timings_ms": {"total": 10},
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_domain",
        json={"workspace_id": "ws-1", "prompt": prompt, "debug": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["plan_json_v2"]["base_domain_id"] == 21
    assert "age_extreme_prompt" in resp.json["debug"]["rerank_signals"]
    assert resp.json["sql_json"]["sorting"][0]["col"]["columnName"] == "birth_date"


def test_plan_domain_route_birth_month_workflow_payload_survives_http_boundary(client, monkeypatch):
    prompt = "Show me all the students who have a birthday in March"
    golden_debug = _load_golden_debug("birth_month")

    class _Svc:
        def plan(self, payload, *, user_id):
            assert payload["prompt"] == prompt
            assert payload["workspace_id"] == "ws-1"
            assert user_id == "user-1"
            return {
                "plan_json_v2": {
                    "schema_version": 2,
                    "base_domain_id": 21,
                    "domain_name": "Student Demographics And Enrollment",
                },
                "sql_json": {
                    "version": 1,
                    "domainId": 21,
                    "filters": {
                        "type": "group",
                        "match": "and",
                        "children": [
                            {
                                "type": "condition",
                                "field": {"exprId": "dp:date_part:month:id:14750", "columnName": "birth_date_month"},
                                "op": "equals",
                                "value": 3,
                            }
                        ],
                    },
                    "dataPrep": {
                        "rules": [
                            {
                                "id": "dp:date_part:month:id:14750",
                                "op": "date_part",
                                "part": "month",
                                "output": {"exprId": "dp:date_part:month:id:14750", "columnName": "birth_date_month"},
                            }
                        ]
                    },
                    "meta": {"prompt": prompt},
                },
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "debug": golden_debug,
                "trace_id": "trace-birth-month",
                "timings_ms": {"total": 10},
            }

    monkeypatch.setattr(planner_domain_route, "PlannerDomainService", _Svc)
    resp = client.post(
        "/api/v1/planner/plan_domain",
        json={"workspace_id": "ws-1", "prompt": prompt, "debug": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["plan_json_v2"]["base_domain_id"] == 21
    assert "birth_month_prompt" in resp.json["debug"]["rerank_signals"]
    assert resp.json["sql_json"]["dataPrep"]["rules"][0]["part"] == "month"
    assert resp.json["sql_json"]["filters"]["children"][0]["value"] == 3


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
            raise ForgeError("Pipeline profile not found", status_code=404, details={"trace_id": trace_id})

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
