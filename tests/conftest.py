from __future__ import annotations

import os
from typing import Any, Dict

import pytest

from tests._auth import (
    detect_auth_config,
    discover_workspace_id_inprocess,
    is_jwt_expired,
    login_inprocess,
)

_AUTH_CACHE: Dict[str, Any] = {}

class _DummyTokenManager:
    def start_auto_refresh(self) -> None:
        return None


class _DummyLLM:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class _DummyCohortNERAgent:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class _DummyValkeyClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def rpush(self, *args: Any, **kwargs: Any) -> int:
        return 0


class _DummyValkeyModule:
    StrictValkey = _DummyValkeyClient


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    from app import factory

    monkeypatch.setattr(factory, "DatabricksTokenManager", _DummyTokenManager)
    monkeypatch.setattr(factory, "SigmaTokenManager", _DummyTokenManager)
    monkeypatch.setattr(factory, "OpenAILLMClient", _DummyLLM)
    monkeypatch.setattr(factory, "CohortNERAgent", _DummyCohortNERAgent)
    monkeypatch.setattr(factory, "valkey", _DummyValkeyModule)

    app = factory.create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def test_credentials() -> Dict[str, str]:
    username = os.environ.get("TEST_USERNAME")
    password = os.environ.get("TEST_PASSWORD")
    if not username or not password:
        pytest.skip("Set TEST_USERNAME and TEST_PASSWORD to run auth-dependent tests.")
    return {"username": username, "password": password}


@pytest.fixture
def auth_state(app, client, test_credentials: Dict[str, str]) -> Dict[str, Any]:
    cached_token = _AUTH_CACHE.get("token")
    cached_data = _AUTH_CACHE.get("data")
    if isinstance(cached_token, str) and cached_token and not is_jwt_expired(cached_token):
        return {"token": cached_token, "data": cached_data or {}}

    auth_cfg = detect_auth_config(app)
    token, data = login_inprocess(
        client,
        auth_cfg["auth_path"],
        test_credentials["username"],
        test_credentials["password"],
    )
    if is_jwt_expired(token):
        token, data = login_inprocess(
            client,
            auth_cfg["auth_path"],
            test_credentials["username"],
            test_credentials["password"],
        )
    _AUTH_CACHE["token"] = token
    _AUTH_CACHE["data"] = data
    return {"token": token, "data": data}


@pytest.fixture
def auth_token(auth_state: Dict[str, Any]) -> str:
    return auth_state["token"]


@pytest.fixture
def workspace_id(app, client, auth_state: Dict[str, Any]) -> str:
    env_ws = os.environ.get("TEST_WORKSPACE_ID")
    if env_ws:
        return env_ws
    ws_id = discover_workspace_id_inprocess(client, app, auth_state["token"], auth_state.get("data"))
    if not ws_id:
        pytest.skip("Unable to determine workspace id; set TEST_WORKSPACE_ID to proceed.")
    return ws_id


@pytest.fixture
def auth_headers(
    monkeypatch: pytest.MonkeyPatch,
    auth_token: str,
    workspace_id: str,
) -> Dict[str, str]:
    from app import factory
    from app.decorators import security

    def _verify_token(token: str) -> Dict[str, Any]:
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    return {
        "Authorization": f"Bearer {auth_token}",
        "X-Workspace-Id": workspace_id,
        "X-User-Id": "user-1",
    }


@pytest.fixture
def invalid_auth_headers(monkeypatch: pytest.MonkeyPatch) -> Dict[str, str]:
    from app import factory
    from app.decorators import security

    def _verify_token(token: str) -> None:
        return None

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", lambda token: {})
    return {
        "Authorization": "Bearer bad-token",
        "X-Workspace-Id": "ws-1",
        "X-User-Id": "user-1",
    }
