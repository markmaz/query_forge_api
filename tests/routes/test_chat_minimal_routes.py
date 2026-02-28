from __future__ import annotations

import app.routes.chat_minimal as chat_route
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


def test_minimal_chat_route_returns_service_payload(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_MINIMAL_CHAT_ENABLED", True)
    client.application.config["QF_MINIMAL_CHAT_ENABLED"] = True

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, body, *, workspace_id, user_id):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert body["messages"][0]["content"] == "Hello"
            return {
                "id": "chatcmpl_local_1",
                "model": "qwen2.5",
                "created_at": "2026-02-22T00:00:00Z",
                "message": {"role": "assistant", "content": "Hi"},
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "debug": None,
            }

    monkeypatch.setattr(chat_route, "MinimalChatService", _Svc)
    resp = client.post(
        "/api/v1/chat/minimal",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["message"]["content"] == "Hi"


def test_minimal_chat_route_invalid_request_empty_messages_returns_400(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_MINIMAL_CHAT_ENABLED", True)
    client.application.config["QF_MINIMAL_CHAT_ENABLED"] = True
    resp = client.post(
        "/api/v1/chat/minimal",
        json={"messages": []},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400


def test_minimal_chat_route_missing_workspace_header_returns_400(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_MINIMAL_CHAT_ENABLED", True)
    client.application.config["QF_MINIMAL_CHAT_ENABLED"] = True
    headers = _headers(monkeypatch)
    headers.pop("X-Workspace-Id")
    resp = client.post(
        "/api/v1/chat/minimal",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers=headers,
    )
    assert resp.status_code == 400


def test_minimal_chat_route_workspace_in_body_rejected(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_MINIMAL_CHAT_ENABLED", True)
    client.application.config["QF_MINIMAL_CHAT_ENABLED"] = True
    resp = client.post(
        "/api/v1/chat/minimal",
        json={"workspace_id": "ws-1", "messages": [{"role": "user", "content": "Hello"}]},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400
    assert "header only" in resp.json["error"]


def test_minimal_chat_route_provider_error_maps_to_502(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_MINIMAL_CHAT_ENABLED", True)
    client.application.config["QF_MINIMAL_CHAT_ENABLED"] = True

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, body, *, workspace_id, user_id):
            del body, workspace_id, user_id
            raise ServiceError("Chat provider request failed", status_code=502)

    monkeypatch.setattr(chat_route, "MinimalChatService", _Svc)
    resp = client.post(
        "/api/v1/chat/minimal",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 502


def test_minimal_chat_route_debug_true_returns_debug_payload(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_MINIMAL_CHAT_ENABLED", True)
    client.application.config["QF_MINIMAL_CHAT_ENABLED"] = True

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, body, *, workspace_id, user_id):
            assert body["debug"] is True
            del workspace_id, user_id
            return {
                "id": "chatcmpl_local_1",
                "model": "qwen2.5",
                "created_at": "2026-02-22T00:00:00Z",
                "message": {"role": "assistant", "content": "Hi"},
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "debug": {"provider_model": "qwen2.5", "finish_reason": "stop"},
            }

    monkeypatch.setattr(chat_route, "MinimalChatService", _Svc)
    resp = client.post(
        "/api/v1/chat/minimal",
        json={"messages": [{"role": "user", "content": "Hello"}], "debug": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["debug"]["finish_reason"] == "stop"
