from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.config.llm_resolver as resolver
from app.exceptions.forge_error import ForgeError


def test_resolve_llm_config_returns_db_config() -> None:
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = {
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "api_key": "sk-real",
        "endpoint_url": "https://api.openai.com/v1",
        "role": "planner",
    }
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        result = resolver.resolve_llm_config("ws1", "planner")
    assert result is not None
    assert result["provider"] == "openai"
    assert result["api_key"] == "sk-real"
    mock_service.get_llm_for_role.assert_called_once_with("ws1", "planner")


def test_resolve_llm_config_returns_none_when_not_configured() -> None:
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = None
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        result = resolver.resolve_llm_config("ws1", "ner")
    assert result is None


def test_resolve_llm_config_uses_workspace_any_role_fallback() -> None:
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = {
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "api_key": "sk-real",
        "endpoint_url": "",
        "role": "planner",
        "_source": "workspace_any_role",
    }
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        result = resolver.resolve_llm_config("ws1", "ner")
    assert result is not None
    assert result["_source"] == "workspace_any_role"


def test_resolve_llm_config_handles_service_exception() -> None:
    mock_service = MagicMock()
    mock_service.get_llm_for_role.side_effect = RuntimeError("DB down")
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        result = resolver.resolve_llm_config("ws1", "planner")
    assert result is None


def test_resolve_llm_config_surfaces_unexpected_service_errors() -> None:
    mock_service = MagicMock()
    mock_service.get_llm_for_role.side_effect = AssertionError("unexpected service bug")
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        with pytest.raises(AssertionError, match="unexpected service bug"):
            resolver.resolve_llm_config("ws1", "planner")


def test_build_llm_client_for_role_uses_override_id() -> None:
    mock_service = MagicMock()
    mock_service.get_internal_by_id.return_value = {
        "id": 17,
        "workspace_id": "ws1",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "role": "planner",
        "is_active": 1,
        "endpoint_url": "https://api.openai.com/v1",
        "api_key": "sk-override",
    }
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        runtime = resolver.build_llm_client_for_role(
            workspace_id="ws1",
            role="planner",
            llm_id_override=17,
        )
    assert runtime.llm_id == 17
    assert runtime.source == "override"
    assert runtime.model == "gpt-4o-mini"
    mock_service.get_internal_by_id.assert_called_once_with(17)


def test_build_llm_client_for_role_rejects_override_workspace_mismatch() -> None:
    mock_service = MagicMock()
    mock_service.get_internal_by_id.return_value = {
        "id": 99,
        "workspace_id": "ws-other",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "role": "planner",
        "is_active": 1,
        "endpoint_url": "https://api.openai.com/v1",
    }
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        with pytest.raises(ForgeError) as exc:
            resolver.build_llm_client_for_role(
                workspace_id="ws1",
                role="planner",
                llm_id_override=99,
            )
    assert exc.value.status_code == 403


def test_build_llm_client_for_role_requires_api_key_for_openai() -> None:
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = {
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "api_key": None,
        "endpoint_url": "https://api.openai.com/v1",
        "role": "planner",
    }
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        with pytest.raises(ForgeError) as exc:
            resolver.build_llm_client_for_role(workspace_id="ws1", role="planner")
    assert exc.value.status_code == 400


def test_to_int_or_none_returns_none_for_invalid_values() -> None:
    assert resolver._to_int_or_none("abc") is None
    assert resolver._to_int_or_none(None) is None


def test_to_int_or_none_surfaces_unexpected_int_conversion_errors() -> None:
    class _BrokenInt:
        def __int__(self) -> int:
            raise AssertionError("unexpected int conversion bug")

    with pytest.raises(AssertionError, match="unexpected int conversion bug"):
        resolver._to_int_or_none(_BrokenInt())
