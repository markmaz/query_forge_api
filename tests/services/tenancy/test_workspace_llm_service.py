from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_sql():
    return MagicMock()


@pytest.fixture
def service(mock_sql):
    from app.services.tenancy.workspace_llm_service import WorkspaceLLMService
    return WorkspaceLLMService(sql=mock_sql)


def _make_row(role="planner", encrypted_key=None):
    return {
        "id": 1,
        "workspace_id": "ws1",
        "name": "GPT-4 Planner",
        "provider": "openai",
        "model_name": "gpt-4o",
        "role": role,
        "api_key_encrypted": encrypted_key,
        "endpoint_url": None,
        "is_active": 1,
        "config_json": None,
        "created_at": None,
        "updated_at": None,
    }


# ── get_all_for_workspace ──────────────────────────────────────────────────────

def test_get_all_for_workspace_returns_list(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [_make_row()]
    result = service.get_all_for_workspace("ws1")
    assert len(result) == 1
    assert result[0]["role"] == "planner"
    assert "api_key_encrypted" not in result[0]
    assert result[0]["has_api_key"] is False


def test_get_all_for_workspace_has_api_key_true(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [_make_row(encrypted_key="gAAAAABenc...")]
    with patch("app.services.tenancy.workspace_llm_service.decrypt_api_key", return_value="sk-real"):
        result = service.get_all_for_workspace("ws1")
    assert result[0]["has_api_key"] is True
    assert "api_key_encrypted" not in result[0]


# ── get_llm_for_role ──────────────────────────────────────────────────────────

def test_get_llm_for_role_returns_db_config(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [_make_row(encrypted_key="enc_key")]
    with patch("app.services.tenancy.workspace_llm_service.decrypt_api_key", return_value="sk-real"):
        result = service.get_llm_for_role("ws1", "planner")
    assert result is not None
    assert result["provider"] == "openai"
    assert result["api_key"] == "sk-real"


def test_get_llm_for_role_falls_back_to_env(service, mock_sql, monkeypatch):
    mock_sql.execute_query_mappings.return_value = []
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("VLLM_MODEL", "qwen25-7b")
    result = service.get_llm_for_role("ws1", "planner")
    assert result is not None
    assert result["provider"] == "generic"
    assert result["endpoint_url"] == "http://localhost:8000"


def test_get_llm_for_role_returns_none_when_nothing_configured(service, mock_sql, monkeypatch):
    mock_sql.execute_query_mappings.return_value = []
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.delenv("SEMANTIC_LLM_ENDPOINT", raising=False)
    monkeypatch.delenv("SEMANTIC_LLM_MODEL", raising=False)
    monkeypatch.delenv("SEMANTIC_PLAN_LLM_MODEL", raising=False)
    result = service.get_llm_for_role("ws1", "planner")
    assert result is None


# ── create_llm — unique active constraint ─────────────────────────────────────

def test_create_llm_enforces_one_active_per_role(service, mock_sql):
    # Simulate existing active record
    mock_sql.execute_query_mappings.return_value = [{"id": 99}]
    with pytest.raises(ValueError, match="already has an active LLM"):
        service.create_llm("ws1", {
            "name": "Duplicate",
            "provider": "openai",
            "model_name": "gpt-4o",
            "role": "planner",
            "is_active": True,
        })


def test_create_llm_encrypts_api_key(service, mock_sql):
    # First call: check existing active (none) → Second call: fetch newly created row
    mock_sql.execute_query_mappings.side_effect = [
        [],  # check for existing active
        [_make_row(encrypted_key="enc")],  # fetch after insert
    ]
    mock_sql.execute_write.return_value = None
    with patch("app.services.tenancy.workspace_llm_service.encrypt_api_key", return_value="enc_val"):
        result = service.create_llm("ws1", {
            "name": "Test",
            "provider": "openai",
            "model_name": "gpt-4o",
            "role": "planner",
            "api_key": "sk-plaintext",
            "is_active": True,
        })
    assert result is not None
    assert "api_key" not in result  # raw key never in public dict


# ── API key masking ───────────────────────────────────────────────────────────

def test_masked_api_key_in_response(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [_make_row(encrypted_key="gAAAAAB_encrypted")]
    with patch("app.services.tenancy.workspace_llm_service.decrypt_api_key", return_value="sk-1234567890abcdef"):
        result = service.get_all_for_workspace("ws1")
    assert result[0].get("api_key") is None
    assert result[0].get("api_key_encrypted") is None
    assert result[0]["masked_api_key"] is not None
    assert "1234567890abcdef" not in str(result[0]["masked_api_key"])


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_llm_calls_execute_write(service, mock_sql):
    service.delete_llm(42)
    mock_sql.execute_write.assert_called_once()
    call_args = mock_sql.execute_write.call_args
    assert "DELETE" in call_args[0][0].upper()
