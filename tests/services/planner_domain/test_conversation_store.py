"""Unit tests for app.services.planner_domain.conversation_store."""
import pytest

import app.services.planner_domain.conversation_store as conversation_store_module
from app.services.planner_domain.conversation_store import HybridPlannerDomainConversationStore


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch):
    monkeypatch.setattr(conversation_store_module, "_IN_MEMORY_CONV_STORE", {})
    monkeypatch.setattr(conversation_store_module, "_valkey_client", None)


def test_get_state_returns_none_for_invalid_json():
    store = HybridPlannerDomainConversationStore()
    conversation_store_module._IN_MEMORY_CONV_STORE["planner:domain:ws:user:conv"] = "{bad json"

    out = store.get_state(workspace_id="ws", user_id="user", conversation_id="conv")

    assert out is None


def test_get_state_falls_back_to_memory_when_valkey_read_fails():
    class _FailingClient:
        def get(self, key):
            del key
            raise conversation_store_module.ValkeyError("valkey unavailable")

    conversation_store_module._IN_MEMORY_CONV_STORE["planner:domain:ws:user:conv"] = '{"trace_id":"trace-1"}'
    monkeypatch_client = _FailingClient()
    conversation_store_module._valkey_client = monkeypatch_client

    store = HybridPlannerDomainConversationStore()
    out = store.get_state(workspace_id="ws", user_id="user", conversation_id="conv")

    assert out == {"trace_id": "trace-1"}


def test_get_state_surfaces_unexpected_valkey_read_errors():
    class _FailingClient:
        def get(self, key):
            del key
            raise AssertionError("unexpected valkey read failure")

    conversation_store_module._valkey_client = _FailingClient()

    store = HybridPlannerDomainConversationStore()
    with pytest.raises(AssertionError, match="unexpected valkey read failure"):
        store.get_state(workspace_id="ws", user_id="user", conversation_id="conv")


def test_save_state_falls_back_to_memory_when_valkey_write_fails():
    class _FailingClient:
        def setex(self, key, ttl, value):
            del key, ttl, value
            raise conversation_store_module.ValkeyError("valkey unavailable")

    conversation_store_module._valkey_client = _FailingClient()

    store = HybridPlannerDomainConversationStore()
    store.save_state(
        workspace_id="ws",
        user_id="user",
        conversation_id="conv",
        state={"trace_id": "trace-1"},
        qf_ttl_seconds=600,
    )

    assert conversation_store_module._IN_MEMORY_CONV_STORE["planner:domain:ws:user:conv"] == '{"trace_id":"trace-1"}'


def test_save_state_surfaces_unexpected_valkey_write_errors():
    class _FailingClient:
        def setex(self, key, ttl, value):
            del key, ttl, value
            raise AssertionError("unexpected valkey write failure")

    conversation_store_module._valkey_client = _FailingClient()

    store = HybridPlannerDomainConversationStore()
    with pytest.raises(AssertionError, match="unexpected valkey write failure"):
        store.save_state(
            workspace_id="ws",
            user_id="user",
            conversation_id="conv",
            state={"trace_id": "trace-1"},
            qf_ttl_seconds=600,
        )


def test_get_valkey_client_returns_none_on_backend_init_failure(monkeypatch):
    class _FakeValkeyModule:
        class Redis:
            def __init__(self, **kwargs):
                del kwargs
                raise conversation_store_module.ValkeyError("valkey unavailable")

    monkeypatch.setattr(conversation_store_module, "valkey", _FakeValkeyModule())
    monkeypatch.setattr(conversation_store_module, "VALKEY_ADDRESS", "localhost")

    out = conversation_store_module._get_valkey_client()

    assert out is None


def test_get_valkey_client_surfaces_unexpected_init_errors(monkeypatch):
    class _FakeValkeyModule:
        class Redis:
            def __init__(self, **kwargs):
                del kwargs
                raise AssertionError("unexpected valkey init failure")

    monkeypatch.setattr(conversation_store_module, "valkey", _FakeValkeyModule())
    monkeypatch.setattr(conversation_store_module, "VALKEY_ADDRESS", "localhost")

    with pytest.raises(AssertionError, match="unexpected valkey init failure"):
        conversation_store_module._get_valkey_client()
