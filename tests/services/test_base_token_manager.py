from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import base_token_manager


def test_get_token_and_headers(app) -> None:
    with app.app_context():
        app.config["SIGMA_TOKEN_MANAGER"] = SimpleNamespace(token="sig-token")
        token = base_token_manager.get_token(base_token_manager.SIGMA_TOKEN)
        assert token == "sig-token"

        headers = base_token_manager.get_headers(base_token_manager.SIGMA_TOKEN)
        assert headers["Authorization"] == "Bearer sig-token"


def test_get_token_missing(app) -> None:
    with app.app_context():
        with pytest.raises(RuntimeError):
            base_token_manager.get_token("MISSING_TOKEN_MANAGER")
