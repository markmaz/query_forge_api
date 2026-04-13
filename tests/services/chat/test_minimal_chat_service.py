from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.exceptions.forge_error import ForgeError
from app.services.chat.minimal_chat_service import ForgeInsightsChatService, MinimalChatService


class _FakeResponse:
    def __init__(self, status_code: int, body=None, text: str | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else ("" if body is None else str(body))

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeClient:
    def __init__(
        self,
        *,
        response: _FakeResponse | None = None,
        exc: Exception | None = None,
        on_post=None,
        **kwargs,
    ) -> None:
        del kwargs
        self._response = response
        self._exc = exc
        self._on_post = on_post

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def post(self, url: str, json: dict):
        assert url.endswith("/v1/chat/completions")
        assert json["stream"] is False
        if self._on_post is not None:
            self._on_post(url, json)
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


class _MemoryStore:
    def __init__(self) -> None:
        self.rows = {}

    def get_messages(self, *, workspace_id: str, user_id: str, conversation_id: str):
        return self.rows.get((workspace_id, user_id, conversation_id))

    def save_messages(self, *, workspace_id: str, user_id: str, conversation_id: str, messages):
        self.rows[(workspace_id, user_id, conversation_id)] = [dict(m) for m in messages]


class _ConversationStoreV2:
    def __init__(self) -> None:
        self.rows = {}

    def get_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str):
        row = self.rows.get((workspace_id, user_id, conversation_id))
        if row is None:
            return None
        return dict(row)

    def save_conversation(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        conversation,
    ):
        self.rows[(workspace_id, user_id, conversation_id)] = dict(conversation)

    def list_conversations(self, *, workspace_id: str, user_id: str, limit: int):
        del limit
        items = []
        for (ws, uid, conv_id), row in self.rows.items():
            if ws != workspace_id or uid != user_id:
                continue
            items.append(
                {
                    "conversation_id": conv_id,
                    "title": row.get("title"),
                    "last_user_message": row.get("last_user_message"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    "message_count": row.get("message_count"),
                    "has_summary": bool(row.get("summary")),
                }
            )
        return items

    def delete_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str):
        key = (workspace_id, user_id, conversation_id)
        if key not in self.rows:
            return False
        self.rows.pop(key, None)
        return True


def _valid_body(*, debug: bool = False) -> dict:
    return {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 32,
        "debug": debug,
    }


def test_valid_request_returns_normalized_response(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    provider_body = {
        "id": "chatcmpl_provider_1",
        "model": "qwen2.5-test",
        "choices": [{"message": {"role": "assistant", "content": "Hi there"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(response=_FakeResponse(200, body=provider_body), **kwargs),
    )

    svc = MinimalChatService(
        base_url="http://localhost:8000",
        model="qwen2.5-test",
        timeout_seconds=10,
        conversation_store=_MemoryStore(),
    )
    out = svc.chat(_valid_body(), workspace_id="ws-1", user_id="user-1")

    assert out["id"] == "chatcmpl_provider_1"
    assert out["model"] == "qwen2.5-test"
    assert out["conversation_id"].startswith("conv_")
    assert out["message"]["role"] == "assistant"
    assert out["message"]["content"] == "Hi there"
    assert out["usage"]["total_tokens"] == 8
    assert out["debug"] is None


def test_provider_error_maps_to_502(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            response=_FakeResponse(500, body={"error": "boom"}, text='{"error":"boom"}'),
            **kwargs,
        ),
    )
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=_MemoryStore())

    with pytest.raises(ForgeError) as exc:
        svc.chat(_valid_body(), workspace_id="ws-1", user_id="user-1")
    assert exc.value.status_code == 502


def test_provider_http_error_maps_to_502(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            exc=httpx.ConnectError("connection refused", request=httpx.Request("POST", "http://localhost:8000/v1/chat/completions")),
            **kwargs,
        ),
    )
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=_MemoryStore())

    with pytest.raises(ForgeError) as exc:
        svc.chat(_valid_body(), workspace_id="ws-1", user_id="user-1")
    assert exc.value.status_code == 502


def test_provider_unexpected_client_error_surfaces(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(exc=AssertionError("unexpected provider failure"), **kwargs),
    )
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=_MemoryStore())

    with pytest.raises(AssertionError, match="unexpected provider failure"):
        svc.chat(_valid_body(), workspace_id="ws-1", user_id="user-1")


def test_provider_invalid_json_maps_to_502(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            response=_FakeResponse(200, body=ValueError("bad json"), text="not-json"),
            **kwargs,
        ),
    )
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=_MemoryStore())

    with pytest.raises(ForgeError) as exc:
        svc.chat(_valid_body(), workspace_id="ws-1", user_id="user-1")
    assert exc.value.status_code == 502


def test_debug_true_includes_debug_payload(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    provider_body = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {},
    }
    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(response=_FakeResponse(200, body=provider_body, text='{"ok":1}'), **kwargs),
    )
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=_MemoryStore())

    out = svc.chat(_valid_body(debug=True), workspace_id="ws-1", user_id="user-1")
    assert out["debug"] is not None
    assert out["debug"]["finish_reason"] == "stop"
    assert "request_preview" in out["debug"]


def test_invalid_request_empty_messages_raises_400() -> None:
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=_MemoryStore())
    with pytest.raises(ForgeError) as exc:
        svc.chat({"messages": []}, workspace_id="ws-1", user_id="user-1")
    assert exc.value.status_code == 400


def test_conversation_context_is_reused_when_conversation_id_present(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    captured_payloads = []
    provider_responses = [
        _FakeResponse(
            200,
            body={"choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}], "usage": {}},
        ),
        _FakeResponse(
            200,
            body={"choices": [{"message": {"role": "assistant", "content": "Blue."}, "finish_reason": "stop"}], "usage": {}},
        ),
    ]

    def _client_factory(*args, **kwargs):
        return _FakeClient(
            response=provider_responses.pop(0),
            on_post=lambda _url, payload: captured_payloads.append(payload),
            **kwargs,
        )

    monkeypatch.setattr(mod.httpx, "Client", _client_factory)
    store = _MemoryStore()
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=store)

    first = svc.chat({"messages": [{"role": "user", "content": "Hello"}]}, workspace_id="ws-1", user_id="u1")
    conv_id = first["conversation_id"]

    second = svc.chat(
        {
            "conversation_id": conv_id,
            "messages": [{"role": "user", "content": "What color is the sky?"}],
        },
        workspace_id="ws-1",
        user_id="u1",
    )

    assert second["conversation_id"] == conv_id
    assert len(captured_payloads) == 2
    first_messages = captured_payloads[0]["messages"]
    second_messages = captured_payloads[1]["messages"]
    assert first_messages == [{"role": "user", "content": "Hello"}]
    assert second_messages[0]["content"] == "Hello"
    assert second_messages[1]["content"] == "Hi"
    assert second_messages[2]["content"] == "What color is the sky?"


def test_unknown_conversation_id_returns_404(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            response=_FakeResponse(200, body={"choices": [{"message": {"role": "assistant", "content": "ok"}}]}),
            **kwargs,
        ),
    )
    svc = MinimalChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10, conversation_store=_MemoryStore())

    with pytest.raises(ForgeError) as exc:
        svc.chat(
            {"conversation_id": "conv_missing", "messages": [{"role": "user", "content": "Hello"}]},
            workspace_id="ws-1",
            user_id="u1",
        )
    assert exc.value.status_code == 404


def test_forge_insights_uses_fi_conversation_id_prefix(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            response=_FakeResponse(
                200,
                body={"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}], "usage": {}},
            ),
            **kwargs,
        ),
    )

    svc = ForgeInsightsChatService(
        base_url="http://localhost:8000",
        model="qwen",
        timeout_seconds=10,
        conversation_store=_ConversationStoreV2(),
    )
    out = svc.chat(_valid_body(), workspace_id="ws-1", user_id="user-1")
    assert out["conversation_id"].startswith("fi_")


def test_forge_insights_list_get_and_reset_conversation(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            response=_FakeResponse(
                200,
                body={"choices": [{"message": {"role": "assistant", "content": "Ready"}, "finish_reason": "stop"}], "usage": {}},
            ),
            **kwargs,
        ),
    )

    store = _ConversationStoreV2()
    svc = ForgeInsightsChatService(
        base_url="http://localhost:8000",
        model="qwen",
        timeout_seconds=10,
        conversation_store=store,
    )

    created = svc.chat({"messages": [{"role": "user", "content": "Show me principals"}]}, workspace_id="ws-1", user_id="u1")
    conv_id = created["conversation_id"]

    listed = svc.list_conversations(workspace_id="ws-1", user_id="u1")
    assert listed["feature"] == "ForgeInsights"
    assert listed["count"] == 1
    assert listed["items"][0]["conversation_id"] == conv_id

    detail = svc.get_conversation(workspace_id="ws-1", user_id="u1", conversation_id=conv_id)
    assert detail["feature"] == "ForgeInsights"
    assert detail["conversation_id"] == conv_id
    assert detail["message_count"] >= 2

    deleted = svc.reset_conversation(workspace_id="ws-1", user_id="u1", conversation_id=conv_id)
    assert deleted["deleted"] is True

    with pytest.raises(ForgeError) as exc:
        svc.get_conversation(workspace_id="ws-1", user_id="u1", conversation_id=conv_id)
    assert exc.value.status_code == 404


def test_forge_insights_unknown_conversation_id_bootstraps_instead_of_404(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(
        mod.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(
            response=_FakeResponse(
                200,
                body={"choices": [{"message": {"role": "assistant", "content": "Started"}, "finish_reason": "stop"}], "usage": {}},
            ),
            **kwargs,
        ),
    )
    svc = ForgeInsightsChatService(
        base_url="http://localhost:8000",
        model="qwen",
        timeout_seconds=10,
        conversation_store=_ConversationStoreV2(),
    )

    out = svc.chat(
        {
            "conversation_id": "fi_4108afad574b459eb9ef9845ba0ee78b",
            "messages": [{"role": "user", "content": "Hello"}],
        },
        workspace_id="ws-1",
        user_id="u1",
    )
    assert out["conversation_id"] == "fi_4108afad574b459eb9ef9845ba0ee78b"
    assert out["message"]["content"] == "Started"


def test_forge_insights_defaults_to_db_conversation_store(monkeypatch) -> None:
    import app.services.chat.forge_insights_conversation_store as store_mod

    class _Store:
        pass

    monkeypatch.setattr(store_mod, "ForgeInsightsConversationStore", lambda: _Store())
    svc = ForgeInsightsChatService(base_url="http://localhost:8000", model="qwen", timeout_seconds=10)
    assert isinstance(svc._conversation_store, _Store)


def test_list_conversations_tolerates_store_backend_failures() -> None:
    class _FailingStore:
        def list_conversations(self, **kwargs):
            del kwargs
            raise RuntimeError("store unavailable")

    svc = ForgeInsightsChatService(
        base_url="http://localhost:8000",
        model="qwen",
        timeout_seconds=10,
        conversation_store=_FailingStore(),
    )

    out = svc.list_conversations(workspace_id="ws-1", user_id="u1")
    assert out["items"] == []
    assert out["count"] == 0


def test_list_conversations_surfaces_unexpected_store_errors() -> None:
    class _FailingStore:
        def list_conversations(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected list failure")

    svc = ForgeInsightsChatService(
        base_url="http://localhost:8000",
        model="qwen",
        timeout_seconds=10,
        conversation_store=_FailingStore(),
    )

    with pytest.raises(AssertionError, match="unexpected list failure"):
        svc.list_conversations(workspace_id="ws-1", user_id="u1")


def test_reset_conversation_tolerates_store_backend_failures() -> None:
    class _FailingStore:
        def delete_conversation(self, **kwargs):
            del kwargs
            raise RuntimeError("store unavailable")

    svc = ForgeInsightsChatService(
        base_url="http://localhost:8000",
        model="qwen",
        timeout_seconds=10,
        conversation_store=_FailingStore(),
    )

    with pytest.raises(ForgeError) as exc:
        svc.reset_conversation(workspace_id="ws-1", user_id="u1", conversation_id="fi_123")
    assert exc.value.status_code == 404


def test_reset_conversation_surfaces_unexpected_store_errors() -> None:
    class _FailingStore:
        def delete_conversation(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected delete failure")

    svc = ForgeInsightsChatService(
        base_url="http://localhost:8000",
        model="qwen",
        timeout_seconds=10,
        conversation_store=_FailingStore(),
    )

    with pytest.raises(AssertionError, match="unexpected delete failure"):
        svc.reset_conversation(workspace_id="ws-1", user_id="u1", conversation_id="fi_123")


def test_hybrid_conversation_store_falls_back_to_memory_on_valkey_read_failure(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    class _FailingClient:
        def get(self, key):
            del key
            raise mod.ValkeyError("valkey unavailable")

    monkeypatch.setattr(mod, "_valkey_client", _FailingClient())
    monkeypatch.setattr(mod, "_IN_MEMORY_CONV_STORE", {"chat:minimal:ws-1:u1:conv_1": '{"messages":[{"role":"user","content":"Hello"}]}'})

    store = mod.HybridConversationStore(namespace="minimal")
    out = store.get_conversation(workspace_id="ws-1", user_id="u1", conversation_id="conv_1")

    assert out is not None
    assert out["messages"] == [{"role": "user", "content": "Hello"}]


def test_hybrid_conversation_store_drops_expired_memory_entries(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(mod, "_valkey_client", None)
    monkeypatch.setattr(
        mod,
        "_IN_MEMORY_CONV_STORE",
        {
            "chat:minimal:ws-1:u1:conv_1": {
                "value": '{"messages":[{"role":"user","content":"Hello"}]}',
                "stored_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            }
        },
    )

    store = mod.HybridConversationStore(namespace="minimal")
    out = store.get_conversation(workspace_id="ws-1", user_id="u1", conversation_id="conv_1")

    assert out is None
    assert mod._IN_MEMORY_CONV_STORE == {}


def test_hybrid_conversation_store_trims_oldest_memory_entries(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    monkeypatch.setattr(mod, "_valkey_client", None)
    monkeypatch.setattr(mod, "_IN_MEMORY_CONV_STORE", {})
    monkeypatch.setattr(mod, "_MAX_IN_MEMORY_CONVERSATIONS", 2)

    mod._write_in_memory_value("chat:minimal:ws-1:u1:conv_1", '{"messages":[]}', ttl_seconds=600)
    mod._write_in_memory_value("chat:minimal:ws-1:u1:conv_2", '{"messages":[]}', ttl_seconds=600)
    mod._write_in_memory_value("chat:minimal:ws-1:u1:conv_3", '{"messages":[]}', ttl_seconds=600)

    assert "chat:minimal:ws-1:u1:conv_1" not in mod._IN_MEMORY_CONV_STORE
    assert "chat:minimal:ws-1:u1:conv_2" in mod._IN_MEMORY_CONV_STORE
    assert "chat:minimal:ws-1:u1:conv_3" in mod._IN_MEMORY_CONV_STORE


def test_hybrid_conversation_store_surfaces_unexpected_valkey_read_errors(monkeypatch) -> None:
    import app.services.chat.minimal_chat_service as mod

    class _FailingClient:
        def get(self, key):
            del key
            raise AssertionError("unexpected valkey read failure")

    monkeypatch.setattr(mod, "_valkey_client", _FailingClient())

    store = mod.HybridConversationStore(namespace="minimal")
    with pytest.raises(AssertionError, match="unexpected valkey read failure"):
        store.get_conversation(workspace_id="ws-1", user_id="u1", conversation_id="conv_1")
