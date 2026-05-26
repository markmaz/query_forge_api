from __future__ import annotations

from datetime import datetime

import app.features.ai.prompt_feedback_api as prompt_feedback_route
from app.services.prompt_feedback_service import PromptFeedbackWriteResult


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


def test_prompt_feedback_route_creates_feedback(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def save_feedback(self, *, workspace_id, user_id, trace_id, vote, response_json, feedback_comment=None, **kwargs):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert trace_id == "trace-1"
            assert vote == "up"
            assert isinstance(response_json, dict)
            assert feedback_comment is None
            return PromptFeedbackWriteResult(
                id=99,
                vote="up",
                status="recorded",
                created_at=datetime(2026, 1, 1, 12, 0, 0),
                updated_at=datetime(2026, 1, 1, 12, 0, 0),
                created=True,
            )

    monkeypatch.setattr(prompt_feedback_route, "PromptFeedbackService", _Svc)
    resp = client.post(
        "/api/v1/prompt-feedback",
        json={
            "workspace_id": "ws-1",
            "trace_id": "trace-1",
            "vote": "up",
            "response_json": {"answer": "ok"},
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["id"] == 99
    assert resp.json["vote"] == "up"
    assert resp.json["status"] == "recorded"


def test_prompt_feedback_route_updates_feedback_when_service_marks_not_created(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def save_feedback(self, **kwargs):
            del kwargs
            return PromptFeedbackWriteResult(
                id=99,
                vote="down",
                status="analysis_pending",
                created_at=datetime(2026, 1, 1, 12, 0, 0),
                updated_at=datetime(2026, 1, 1, 12, 3, 0),
                created=False,
            )

    monkeypatch.setattr(prompt_feedback_route, "PromptFeedbackService", _Svc)
    resp = client.post(
        "/api/v1/prompt-feedback",
        json={
            "workspace_id": "ws-1",
            "trace_id": "trace-1",
            "vote": "down",
            "response_json": {"answer": "updated"},
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["vote"] == "down"
    assert resp.json["status"] == "analysis_pending"


def test_prompt_feedback_route_accepts_feedback_comment(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def save_feedback(self, *, feedback_comment=None, **kwargs):
            del kwargs
            assert feedback_comment == "The chosen domain was incorrect"
            return PromptFeedbackWriteResult(
                id=101,
                vote="down",
                status="analysis_pending",
                created_at=datetime(2026, 1, 1, 12, 0, 0),
                updated_at=datetime(2026, 1, 1, 12, 0, 0),
                created=True,
            )

    monkeypatch.setattr(prompt_feedback_route, "PromptFeedbackService", _Svc)
    resp = client.post(
        "/api/v1/prompt-feedback",
        json={
            "workspace_id": "ws-1",
            "trace_id": "trace-2",
            "vote": "thumbs_down",
            "feedback_comment": "The chosen domain was incorrect",
            "response_json": {"answer": "nope"},
        },
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 201
    assert resp.json["status"] == "analysis_pending"


def test_prompt_feedback_route_rejects_invalid_vote(client, monkeypatch):
    resp = client.post(
        "/api/v1/prompt-feedback",
        json={
            "workspace_id": "ws-1",
            "trace_id": "trace-1",
            "vote": "invalid",
            "response_json": {"answer": "ok"},
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400


def test_prompt_feedback_route_rejects_missing_response_json(client, monkeypatch):
    resp = client.post(
        "/api/v1/prompt-feedback",
        json={
            "workspace_id": "ws-1",
            "trace_id": "trace-1",
            "vote": "up",
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400


def test_prompt_feedback_route_rejects_payload_too_large(client, monkeypatch):
    monkeypatch.setattr(prompt_feedback_route, "QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES", 100)
    resp = client.post(
        "/api/v1/prompt-feedback",
        json={
            "workspace_id": "ws-1",
            "vote": "up",
            "response_json": {"payload": "x" * 500},
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 413
