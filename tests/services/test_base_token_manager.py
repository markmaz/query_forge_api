from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.exceptions.forge_error import ForgeError
from app.services import base_token_manager


def test_get_token_and_headers(app) -> None:
    with app.app_context():
        app.config["SIGMA_TOKEN_MANAGER"] = SimpleNamespace(token="sig-token")
        token = base_token_manager.fetch_forge_token(base_token_manager.QF_SIGMA_TOKEN)
        assert token == "sig-token"

        headers = base_token_manager.forge_auth_headers(base_token_manager.QF_SIGMA_TOKEN)
        assert headers["Authorization"] == "Bearer sig-token"


def test_get_token_missing(app) -> None:
    with app.app_context():
        with pytest.raises(ForgeError) as exc:
            base_token_manager.fetch_forge_token("MISSING_TOKEN_MANAGER")
        assert exc.value.status_code == 503


def test_get_databricks_token_from_registry_executor(app) -> None:
    class _Registry:
        def list_datasources(self):
            return [{"name": "primary", "type": "databricks"}]

        def get(self, _name: str):
            return SimpleNamespace(get_bearer_token=lambda: "dbx-registry-token")

    with app.app_context():
        app.extensions["analytics_registry"] = _Registry()
        token = base_token_manager.fetch_forge_token(base_token_manager.QF_DATABRICKS_TOKEN)
        assert token == "dbx-registry-token"
