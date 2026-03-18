from __future__ import annotations

import os
from typing import Any

from flask import current_app

from app.exceptions.forge_error import ForgeError

QF_DATABRICKS_TOKEN = "DATABRICKS_TOKEN_MANAGER"


def _extract_token_from_provider(provider: Any) -> str | None:
    if provider is None:
        return None

    getter = getattr(provider, "get_token", None)
    if callable(getter):
        token = getter()
        if token:
            return str(token)

    fetcher = getattr(provider, "fetch_forge_token", None)
    if callable(fetcher):
        token = fetcher()
        if token:
            return str(token)

    token = getattr(provider, "token", None)
    if token:
        return str(token)

    if callable(provider):
        token = provider()
        if token:
            return str(token)

    return None


def _databricks_oauth_configured() -> bool:
    token_url = (os.getenv("DATABRICKS_TOKEN_URL") or "").strip()
    client_id = (os.getenv("DATABRICKS_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("DATABRICKS_CLIENT_SECRET") or "").strip()
    return bool(token_url.startswith(("http://", "https://")) and client_id and client_secret)


def _token_from_databricks_registry() -> str | None:
    registry = current_app.extensions.get("analytics_registry")
    if registry is None:
        return None

    try:
        ds_list = registry.list_datasources()
    except Exception:
        return None

    names = [str(ds.get("name") or "").strip() for ds in ds_list if str(ds.get("type") or "").strip().lower() == "databricks"]
    names = [n for n in names if n]
    if "primary" in names:
        names = ["primary"] + [n for n in names if n != "primary"]

    for name in names:
        try:
            executor = registry.get(name)
        except Exception:
            continue

        getter = getattr(executor, "get_bearer_token", None)
        if not callable(getter):
            continue

        try:
            token = getter()
        except Exception:
            continue
        if token:
            return str(token)

    return None


def _lazy_bootstrap_databricks_manager() -> Any | None:
    manager = current_app.config.get(QF_DATABRICKS_TOKEN)
    if manager is not None:
        return manager

    if not _databricks_oauth_configured():
        return None

    # Imported lazily to avoid forcing startup coupling.
    from app.adapters.databricks_token_manager import DatabricksForgeTokenPort

    manager = DatabricksForgeTokenPort()
    manager.start_auto_refresh()
    current_app.config[QF_DATABRICKS_TOKEN] = manager
    return manager


def fetch_forge_token(token_manager: str) -> str:
    """
    Generic Token manager - gets or refreshes the token from the given system.

    :param token_manager: The name of the token manager. Should be one of the constants in this class. 
    :type token_manager: str

    Returns:
        The token from the token manager.
    Raises:
        ForgeError: when the given token_manager is missing or not configured.
    """
    key = str(token_manager or "").strip()
    if not key:
        raise ForgeError("Token manager key is required", status_code=503)

    with current_app.app_context():
        provider = current_app.config.get(key)
        token = _extract_token_from_provider(provider)
        if token:
            return token

        if key == QF_DATABRICKS_TOKEN:
            registry_token = _token_from_databricks_registry()
            if registry_token:
                return registry_token

            provider = _lazy_bootstrap_databricks_manager()
            token = _extract_token_from_provider(provider)
            if token:
                return token

        raise ForgeError(f"{key} is not configured in Flask app.", status_code=503)

def forge_auth_headers(token_manager: str):
    """
    Helper method to set the Bearer information for an HTTP request. It gets the correct token for the given system.

    :param token_manager: The name of the token_manager. Should be one of the constants in this class.
    :type token_manager: str

    Returns:
        dict (Header paramerters)
    """
    return {
            "Authorization": f"Bearer {fetch_forge_token(token_manager=token_manager)}",
            "Content-Type": "application/json",
        }
