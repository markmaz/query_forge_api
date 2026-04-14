from __future__ import annotations

import app.features.ai.chat_api as chat_route
from app.exceptions.forge_error import ForgeError


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
            raise ForgeError("Chat provider request failed", status_code=502)

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


def test_forge_insights_chat_route_returns_service_payload(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_FORGE_INSIGHTS_ENABLED", True)
    client.application.config["QF_FORGE_INSIGHTS_ENABLED"] = True

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def ask(self, body, *, workspace_id, user_id, query_args):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert body["messages"][0]["content"] == "Hello"
            assert isinstance(query_args, dict)
            return ({
                "id": "chatcmpl_local_2",
                "model": "qwen2.5",
                "created_at": "2026-03-02T00:00:00Z",
                "conversation_id": "fi_123",
                "message": {"role": "assistant", "content": "ForgeInsights reply"},
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "debug": None,
            }, 200)

    monkeypatch.setattr(chat_route, "ForgeInsightsRouterService", _Svc)
    resp = client.post(
        "/api/v1/chat/forge-insights",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["conversation_id"] == "fi_123"


def test_forge_insights_conversation_list_route_returns_items(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_FORGE_INSIGHTS_ENABLED", True)
    client.application.config["QF_FORGE_INSIGHTS_ENABLED"] = True

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def list_conversations(self, *, workspace_id, user_id, limit):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert limit == 25
            return {
                "feature": "ForgeInsights",
                "count": 1,
                "items": [
                    {
                        "conversation_id": "fi_1",
                        "title": "Show me principals",
                        "created_at": "2026-03-02T00:00:00Z",
                        "updated_at": "2026-03-02T00:01:00Z",
                        "message_count": 6,
                        "last_user_message": "Sort by position",
                        "has_summary": False,
                    }
                ],
            }

    monkeypatch.setattr(chat_route, "ForgeInsightsChatService", _Svc)
    resp = client.get("/api/v1/chat/forge-insights/conversations?limit=25", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["feature"] == "ForgeInsights"
    assert resp.json["count"] == 1
    assert resp.json["items"][0]["conversation_id"] == "fi_1"


def test_forge_insights_conversation_detail_and_delete_routes(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_FORGE_INSIGHTS_ENABLED", True)
    client.application.config["QF_FORGE_INSIGHTS_ENABLED"] = True

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def get_conversation(self, *, workspace_id, user_id, conversation_id):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert conversation_id == "fi_1"
            return {
                "feature": "ForgeInsights",
                "conversation_id": "fi_1",
                "messages": [
                    {"role": "user", "content": "Show me staff at Barksdale"},
                    {"role": "assistant", "content": "Here you go"},
                ],
                "summary": "",
                "title": "Show me staff at Barksdale",
                "created_at": "2026-03-02T00:00:00Z",
                "updated_at": "2026-03-02T00:01:00Z",
                "message_count": 2,
                "last_user_message": "Show me staff at Barksdale",
            }

        def reset_conversation(self, *, workspace_id, user_id, conversation_id):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert conversation_id == "fi_1"
            return {"feature": "ForgeInsights", "conversation_id": "fi_1", "deleted": True}

    monkeypatch.setattr(chat_route, "ForgeInsightsChatService", _Svc)

    detail = client.get("/api/v1/chat/forge-insights/conversations/fi_1", headers=_headers(monkeypatch))
    assert detail.status_code == 200
    assert detail.json["conversation_id"] == "fi_1"
    assert detail.json["message_count"] == 2

    deleted = client.delete("/api/v1/chat/forge-insights/conversations/fi_1", headers=_headers(monkeypatch))
    assert deleted.status_code == 200
    assert deleted.json["deleted"] is True


def test_forge_insights_route_disabled_returns_404(client, monkeypatch):
    monkeypatch.setattr(chat_route, "QF_FORGE_INSIGHTS_ENABLED", False)
    client.application.config["QF_FORGE_INSIGHTS_ENABLED"] = False

    resp = client.post(
        "/api/v1/chat/forge-insights",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 404
