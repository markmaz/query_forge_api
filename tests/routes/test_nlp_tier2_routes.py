from __future__ import annotations

import app.routes.nlp_review as nlp_review
import app.routes.nlp_tier2 as nlp_tier2


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


def test_tier2_parse_route(client, monkeypatch):
    monkeypatch.setattr(
        nlp_tier2,
        "run_tier2_with_meta",
        lambda prompt: {
            "plan_ir": {
                "prompt": prompt,
                "entities": {"subject_entity": "student", "confidence": 0.9},
                "slots": {"names": [{"kind": "unknown", "value": "Holden", "confidence": 0.9}]},
                "topic": ["demographics"],
                "operators": {"negation": False, "comparators": []},
                "intent": {"label": "intent_lookup_by_name", "scores": {"intent_lookup_by_name": 1.0}},
                "warnings": [],
            },
            "model": {"enabled": True, "path": "model-dir", "version": "model-v1"},
            "timings_ms": {"tier2": 12},
        },
    )

    resp = client.post(
        "/api/v1/nlp/tier2/parse",
        json={"workspaceId": "ws-1", "prompt": "Find all the students named Holden"},
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json["plan_ir"]["entities"]["subject_entity"] == "student"
    assert resp.json["plan_ir"]["slots"]["names"][0]["value"] == "Holden"


def test_nlp_review_queue_routes(client, monkeypatch):
    class _Svc:
        def enqueue(self, **kwargs):
            return {
                "id": 1,
                "workspace_id": kwargs["workspace_id"],
                "prompt": kwargs["prompt"],
                "model_version": kwargs["model_version"],
                "prediction": kwargs["prediction_json"],
                "corrected": None,
                "status": "pending",
            }

        def list_items(self, **kwargs):
            return {"rows": [], "count": 0}

        def patch_item(self, **kwargs):
            return {
                "id": kwargs["item_id"],
                "workspace_id": kwargs["workspace_id"],
                "prompt": "p",
                "model_version": "m",
                "prediction": {},
                "corrected": kwargs.get("corrected"),
                "status": kwargs.get("status") or "pending",
            }

        def approve_item(self, **kwargs):
            return {
                "id": kwargs["item_id"],
                "workspace_id": kwargs["workspace_id"],
                "status": "approved",
            }

        def export_item_jsonl(self, **kwargs):
            return {
                "jsonl": "{\"text\":\"x\"}",
                "line": {
                    "text": "x",
                    "entities": [{"start": 0, "end": 1, "label": "VALUE_LITERAL"}],
                    "cats": {"intent_filter": 1.0},
                    "meta": {"workspace_id": kwargs["workspace_id"], "review_item_id": kwargs["item_id"]},
                },
            }

    monkeypatch.setattr(nlp_review, "NLPReviewService", _Svc)
    monkeypatch.setattr(
        nlp_review,
        "run_tier2_with_meta",
        lambda prompt: {
            "plan_ir": {"prompt": prompt, "entities": {"subject_entity": "student", "confidence": 0.8}},
            "model": {"enabled": True, "version": "model-v1"},
            "timings_ms": {"tier2": 5},
        },
    )

    headers = _headers(monkeypatch)

    created = client.post(
        "/api/v1/nlp/review-queue",
        json={"workspaceId": "ws-1", "prompt": "Find all the students named Holden"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json["row"]["status"] == "pending"

    patched = client.patch(
        "/api/v1/nlp/review-queue/1",
        json={"workspaceId": "ws-1", "status": "approved", "corrected": {"entities": [], "cats": {}}},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json["row"]["status"] == "approved"

    exported = client.post("/api/v1/nlp/review-queue/1/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json["line"]["cats"]["intent_filter"] == 1.0
