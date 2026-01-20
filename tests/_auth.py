from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

import pytest
import requests

_TOKEN_KEYS = ("token", "access_token", "jwt", "id_token")
_WORKSPACE_KEYS = ("workspace_id", "workspaceId", "workspaceID", "workspace")


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    if path.startswith("http://") or path.startswith("https://"):
        parsed = urlparse(path)
        path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    return path if path.startswith("/") else f"/{path}"


def detect_auth_config(app) -> Dict[str, Any]:
    env_auth = os.environ.get("TEST_AUTH_URL")
    if env_auth:
        return {"auth_path": _normalize_path(env_auth)}

    candidates: list[tuple[int, str]] = []
    for rule in app.url_map.iter_rules():
        methods = set(rule.methods or [])
        if "POST" not in methods:
            continue
        path = rule.rule or ""
        lowered = path.lower()
        if not any(tag in lowered for tag in ("auth", "login", "token")):
            continue
        score = 0
        if "/auth" in lowered:
            score += 2
        if lowered.endswith("/auth"):
            score += 3
        if "login" in lowered:
            score += 1
        candidates.append((score, path))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return {"auth_path": _normalize_path(candidates[0][1])}

    pytest.skip("Unable to detect auth endpoint; set TEST_AUTH_URL to proceed.")
    return {}


def detect_auth_url_live(base_url: str) -> str:
    env_auth = os.environ.get("TEST_AUTH_URL")
    if env_auth:
        if env_auth.startswith("http://") or env_auth.startswith("https://"):
            return env_auth
        return urljoin(base_url.rstrip("/") + "/", env_auth.lstrip("/"))

    candidates = [
        "/auth/auth",
        "/api/v1/auth/auth",
        "/auth/login",
        "/api/v1/auth/login",
        "/login",
        "/api/login",
        "/token",
        "/api/token",
    ]
    for candidate in candidates:
        url = urljoin(base_url.rstrip("/") + "/", candidate.lstrip("/"))
        try:
            resp = requests.post(url, json={}, timeout=10)
        except requests.RequestException:
            continue
        if resp.status_code in (200, 400, 401):
            return url

    pytest.skip("Unable to detect auth endpoint; set TEST_AUTH_URL to proceed.")
    return ""


def build_login_payloads(username: str, password: str, preferred_key: Optional[str] = None) -> list[Dict[str, str]]:
    keys: list[str] = []
    if preferred_key:
        keys.append(preferred_key)
    for key in ("username", "email"):
        if key not in keys:
            keys.append(key)
    return [{key: username, "password": password} for key in keys if key]


def parse_token(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        for key in _TOKEN_KEYS:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in _TOKEN_KEYS:
                val = nested.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return None


def parse_workspace_id(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        for key in _WORKSPACE_KEYS:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                inner = val.get("id") or val.get("workspace_id")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
    return None


def is_jwt_expired(token: str, leeway_seconds: int = 60) -> bool:
    parts = (token or "").split(".")
    if len(parts) != 3:
        return False
    try:
        payload = _b64decode(parts[1])
        data = json.loads(payload)
    except Exception:
        return False
    exp = data.get("exp")
    if not exp:
        return False
    try:
        exp_ts = int(exp)
    except Exception:
        return False
    return time.time() >= (exp_ts - int(leeway_seconds))


def user_id_from_token(token: str) -> Optional[str]:
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    try:
        payload = _b64decode(parts[1])
        data = json.loads(payload)
    except Exception:
        return None
    for key in ("sub", "user_id", "uid", "username", "email"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def login_inprocess(client, auth_path: str, username: str, password: str) -> Tuple[str, Dict[str, Any]]:
    last_status = None
    for payload in build_login_payloads(username, password):
        resp = client.post(_normalize_path(auth_path), json=payload)
        last_status = resp.status_code
        if resp.status_code not in (200, 201):
            continue
        data = resp.get_json(silent=True) or {}
        token = parse_token(data)
        if token:
            return token, data
    pytest.skip(f"Login failed for in-process tests (status={last_status}).")
    return "", {}


def login_live(auth_url: str, username: str, password: str) -> Tuple[str, Dict[str, Any]]:
    last_status = None
    for payload in build_login_payloads(username, password):
        try:
            resp = requests.post(auth_url, json=payload, timeout=15)
        except requests.RequestException:
            continue
        last_status = resp.status_code
        if resp.status_code not in (200, 201):
            continue
        try:
            data = resp.json() or {}
        except ValueError:
            data = {}
        token = parse_token(data)
        if token:
            return token, data
    pytest.skip(f"Login failed for live tests (status={last_status}).")
    return "", {}


def discover_workspace_id_inprocess(client, app, token: str, login_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    if login_data:
        ws_id = parse_workspace_id(login_data)
        if ws_id:
            return ws_id

    for rule in app.url_map.iter_rules():
        if rule.arguments:
            continue
        if "GET" not in set(rule.methods or []):
            continue
        if "workspaces" not in (rule.rule or "").lower():
            continue
        resp = client.get(
            rule.rule,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            continue
        data = resp.get_json(silent=True)
        ws_id = _extract_workspace_from_collection(data)
        if ws_id:
            return ws_id
    return None


def discover_workspace_id_live(base_url: str, headers: Dict[str, str], login_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    if login_data:
        ws_id = parse_workspace_id(login_data)
        if ws_id:
            return ws_id

    candidates = ["/api/v1/workspaces/", "/api/v1/workspaces", "/workspaces/"]
    for candidate in candidates:
        url = urljoin(base_url.rstrip("/") + "/", candidate.lstrip("/"))
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except ValueError:
            data = None
        ws_id = _extract_workspace_from_collection(data)
        if ws_id:
            return ws_id
    return None


def _extract_workspace_from_collection(data: Any) -> Optional[str]:
    if isinstance(data, list) and data:
        for item in data:
            ws_id = parse_workspace_id(item)
            if ws_id:
                return ws_id
    if isinstance(data, dict):
        rows = data.get("rows") or data.get("data")
        if isinstance(rows, list):
            for item in rows:
                ws_id = parse_workspace_id(item)
                if ws_id:
                    return ws_id
    return None


def _b64decode(segment: str) -> str:
    padded = segment + "=" * (-len(segment) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
    return raw.decode("utf-8")
