from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.adapters.base_token_manager import BaseForgeTokenManager


def test_refresh_token_ignores_expected_request_failures() -> None:
    manager = BaseForgeTokenManager(
        name="forge",
        token_url="https://auth.example.com/token",
        client_id="client",
        client_secret="secret",
    )

    with patch("app.adapters.base_token_manager.requests.post", side_effect=requests.RequestException("network down")):
        manager.refresh_token()

    assert manager._token is None


def test_refresh_token_surfaces_unexpected_errors() -> None:
    manager = BaseForgeTokenManager(
        name="forge",
        token_url="https://auth.example.com/token",
        client_id="client",
        client_secret="secret",
    )

    with patch("app.adapters.base_token_manager.requests.post", side_effect=AssertionError("unexpected token bug")):
        with pytest.raises(AssertionError, match="unexpected token bug"):
            manager.refresh_token()


def test_refresh_token_sets_access_token_on_success() -> None:
    manager = BaseForgeTokenManager(
        name="forge",
        token_url="https://auth.example.com/token",
        client_id="client",
        client_secret="secret",
    )
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "token-123"}

    with patch("app.adapters.base_token_manager.requests.post", return_value=response):
        manager.refresh_token()

    assert manager.token == "token-123"
