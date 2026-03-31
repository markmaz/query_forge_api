from __future__ import annotations

import app.features.ai.ai_api as ai_routes


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


def test_ai_suggest_semantic_adapter_returns_suggest_contract(client, monkeypatch):
    class _PlanService:
        def plan(self, payload, *, include_llm=True):
            assert payload["workspace_id"] == "ws-1"
            assert include_llm is True
            return {
                "llm_plan": {
                    "model": "qwen25-14b",
                    "sql_json": {
                        "domainId": 77,
                        "columns": [
                            {
                                "field": {
                                    "modelColumnId": 101,
                                    "columnName": "k_student",
                                    "workspaceTableId": 11,
                                    "exprId": None,
                                    "alias": None,
                                },
                                "alias": None,
                            }
                        ],
                        "filters": {
                            "type": "group",
                            "id": "f1",
                            "match": "and",
                            "children": [
                                {
                                    "type": "condition",
                                    "id": "c1",
                                    "field": {
                                        "modelColumnId": 202,
                                        "columnName": "is_el",
                                        "workspaceTableId": 12,
                                        "exprId": None,
                                        "alias": None,
                                    },
                                    "op": "equals",
                                    "value": True,
                                }
                            ],
                        },
                    },
                    "confidence": 0.81,
                    "notes": ["ok"],
                }
            }

    monkeypatch.setattr(ai_routes, "PlanService", _PlanService)

    resp = client.post(
        "/api/v1/ai/suggest-semantic-adapter",
        json={
            "mode": "ai_first",
            "prompt": "How many EL students were chronically absent last year?",
            "workspaceId": "ignored-by-header",
            "currentSqlJson": None,
            "domainContext": {"selectedDomainId": 77, "domainCandidates": []},
            "candidates": {"tables": [], "columns": []},
        },
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    body = resp.json
    assert "edits" in body
    assert "sqlJson" in body
    assert body["debug"]["model"] == "qwen25-14b"
    assert any(item.get("op") == "setDomain" for item in body["edits"])
    assert any(item.get("op") == "addSelect" for item in body["edits"])
    assert any(item.get("op") == "addFilter" for item in body["edits"])


def test_ai_suggest_semantic_adapter_validates_request(client, monkeypatch):
    resp = client.post(
        "/api/v1/ai/suggest-semantic-adapter",
        json={"prompt": "missing mode"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400


def test_ai_suggest_semantic_adapter_uses_current_sqljson_domain_and_vertical_default(client, monkeypatch):
    client.application.config["SEMANTIC_VERTICAL_DEFAULT"] = "education"

    class _PlanService:
        def plan(self, payload, *, include_llm=True):
            assert include_llm is True
            assert payload["domain_id"] == 6
            assert payload["vertical_norm"] == "education"
            return {
                "llm_plan": {
                    "model": "qwen25-14b",
                    "sql_json": {"domainId": 6, "columns": [], "filters": None},
                    "confidence": 0.7,
                    "notes": ["ok"],
                }
            }

    monkeypatch.setattr(ai_routes, "PlanService", _PlanService)

    resp = client.post(
        "/api/v1/ai/suggest-semantic-adapter",
        json={
            "mode": "ai_first",
            "prompt": "students in montgomery county",
            "workspaceId": "ignored-by-header",
            "currentSqlJson": {"domainId": 6},
            "candidates": {"tables": [], "columns": []},
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["sqlJson"]["domainId"] == 6


def test_ai_suggest_deprecated_wrapper_uses_semantic_plan(client, monkeypatch):
    class _PlanService:
        def plan(self, payload, *, include_llm=True):
            assert include_llm is True
            assert payload["workspace_id"] == "ws-1"
            assert payload["domain_id"] == 6
            return {
                "llm_plan": {
                    "model": "qwen25-14b",
                    "sql_json": {
                        "domainId": 6,
                        "columns": [
                            {
                                "field": {
                                    "modelColumnId": 266,
                                    "columnName": "lea_name",
                                    "workspaceTableId": 20,
                                    "exprId": None,
                                    "alias": None,
                                },
                                "alias": None,
                            }
                        ],
                        "filters": None,
                    },
                    "confidence": 0.7,
                    "notes": ["semantic"],
                }
            }

    monkeypatch.setattr(ai_routes, "PlanService", _PlanService)

    resp = client.post(
        "/api/v1/ai/suggest",
        json={
            "mode": "columns",
            "prompt": "show districts",
            "workspaceId": "ignored-by-header",
            "currentSqlJson": {"domainId": 6},
            "candidates": {"tables": [], "columns": []},
        },
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.headers["X-QueryForge-Deprecated"] == "true"
    assert resp.headers["X-QueryForge-Replacement"] == "/api/v1/semantic/plan"
    assert resp.json["sqlJson"]["meta"]["semantic_plan_placeholders"]["columns"]["status"] == "requested"
    assert any(item.get("op") == "setDomain" for item in resp.json["edits"])
