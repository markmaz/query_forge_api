from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_resolve_llm_config_returns_db_config():
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = {
        "provider": "openai",
        "model_name": "gpt-4o",
        "api_key": "sk-real",
        "endpoint_url": None,
        "role": "planner",
    }
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        import importlib
        import app.config.llm_resolver as resolver
        importlib.reload(resolver)
        result = resolver.resolve_llm_config("ws1", "planner")
    assert result is not None
    assert result["provider"] == "openai"
    assert result["api_key"] == "sk-real"
    mock_service.get_llm_for_role.assert_called_once_with("ws1", "planner")


def test_resolve_llm_config_returns_none_when_not_configured():
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = None
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        import importlib
        import app.config.llm_resolver as resolver
        importlib.reload(resolver)
        result = resolver.resolve_llm_config("ws1", "ner")
    assert result is None


def test_resolve_llm_config_handles_service_exception():
    mock_service = MagicMock()
    mock_service.get_llm_for_role.side_effect = RuntimeError("DB down")
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        import importlib
        import app.config.llm_resolver as resolver
        importlib.reload(resolver)
        result = resolver.resolve_llm_config("ws1", "planner")
    assert result is None
