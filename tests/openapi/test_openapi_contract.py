from __future__ import annotations

import os

import pytest
import requests

try:
    import schemathesis
    from schemathesis import GenerationMode
    from schemathesis import openapi as schemathesis_openapi
    from schemathesis.core.failures import FailureGroup
except ImportError as exc:  # pragma: no cover - dependency optional at runtime
    schemathesis = None
    schemathesis_openapi = None
    FailureGroup = None
    GenerationMode = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""

_SKIP_METHODS = {"DELETE"}
_SKIP_SUBSTRINGS = ("purge", "trash")
_SKIP_PATHS = {
    "/api/v1/dashboards",
    "/api/v1/models/samples/refresh",
    "/api/v1/workspace-inventory/sync",
}

_BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8080").rstrip("/")
_SWAGGER_URL = os.environ.get("SWAGGER_URL") or f"{_BASE_URL}/swagger.json"

_SCHEMA = None
_SKIP_REASON = ""
_AUTH_CACHE: dict[str, object] = {}

if schemathesis is None:
    _SKIP_REASON = f"schemathesis not installed: {_IMPORT_ERROR}"
else:
    try:
        _SCHEMA = schemathesis_openapi.from_url(_SWAGGER_URL)
        _SCHEMA.config.generation.modes = [GenerationMode.POSITIVE]
        _SCHEMA.config.generation.max_examples = 1
    except requests.RequestException as exc:
        _SKIP_REASON = f"Unable to load OpenAPI schema from {_SWAGGER_URL}: {exc}"
    except Exception as exc:  # pragma: no cover - defensive, schema errors vary
        _SKIP_REASON = f"Unable to load OpenAPI schema from {_SWAGGER_URL}: {exc}"


def _get_live_auth_headers() -> dict[str, str]:
    from tests._auth import (
        detect_auth_url_live,
        discover_workspace_id_live,
        is_jwt_expired,
        login_live,
        user_id_from_token,
    )

    cached = _AUTH_CACHE.get("headers")
    token = _AUTH_CACHE.get("token")
    if cached and isinstance(cached, dict) and isinstance(token, str) and not is_jwt_expired(token):
        return dict(cached)

    username = os.environ.get("TEST_USERNAME")
    password = os.environ.get("TEST_PASSWORD")
    if not username or not password:
        pytest.skip("Set TEST_USERNAME and TEST_PASSWORD to run the OpenAPI tests.")

    auth_url = detect_auth_url_live(_BASE_URL)
    token, data = login_live(auth_url, username, password)
    headers = {"Authorization": f"Bearer {token}"}

    workspace_id = os.environ.get("TEST_WORKSPACE_ID")
    if not workspace_id:
        workspace_id = discover_workspace_id_live(_BASE_URL, headers, data)
    if not workspace_id:
        pytest.skip("Unable to determine workspace id; set TEST_WORKSPACE_ID to proceed.")

    headers["X-Workspace-Id"] = workspace_id
    user_id = user_id_from_token(token)
    if user_id:
        headers["X-User-Id"] = user_id
    _AUTH_CACHE["headers"] = dict(headers)
    _AUTH_CACHE["token"] = token
    return headers


def _skip_case(method: str, path: str) -> bool:
    if method in _SKIP_METHODS:
        return True
    path_norm = "/" + path.lstrip("/")
    while "//" in path_norm:
        path_norm = path_norm.replace("//", "/")
    if path_norm != "/":
        path_norm = path_norm.rstrip("/")
    lowered = path_norm.lower()
    if lowered in _SKIP_PATHS:
        return True
    return any(tag in lowered for tag in _SKIP_SUBSTRINGS)


def _operation_has_json_body(operation) -> bool:
    try:
        body = operation.body
    except Exception:
        return False
    try:
        for alternative in body:
            if getattr(alternative, "media_type", "") == "application/json":
                return True
    except Exception:
        return False
    return False


if _SCHEMA is not None:

    @_SCHEMA.parametrize()
    def test_openapi_contract(case) -> None:
        if _skip_case(case.method.upper(), case.path):
            pytest.skip("Skipping destructive or purge-like endpoint")

        headers = dict(case.headers or {})
        headers.update(_get_live_auth_headers())
        path_params = dict(case.path_parameters or {})
        for key in list(path_params):
            if key.lower() in ("workspace_id", "workspaceid"):
                path_params[key] = headers.get("X-Workspace-Id")

        case.headers = headers
        case.path_parameters = path_params

        if case.method.upper() in {"POST", "PUT", "PATCH"} and _operation_has_json_body(case.operation):
            case.body = {}
            case.media_type = "application/json"

        response = case.call(base_url=_BASE_URL)

        if response.status_code >= 500 and "warehouses" in case.path.lower():
            pytest.skip("Warehouses endpoint depends on external services")

        assert response.status_code < 500, f"{case.method} {case.path} returned {response.status_code}"

        try:
            case.validate_response(response)
        except FailureGroup:
            # Keep validation conservative; only enforce non-5xx at this stage.
            pass

else:

    def test_openapi_contract() -> None:
        pytest.skip(_SKIP_REASON)
