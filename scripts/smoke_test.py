#!/usr/bin/env python3
"""
QueryForge pre-release smoke test.

Usage:
    python scripts/smoke_test.py [OPTIONS]

Options:
    --base-url       API root URL (overrides QF_BASE_URL env var)
    --username       Login username (overrides QF_USERNAME)
    --password       Login password (overrides QF_PASSWORD)
    --workspace-id   Workspace ID (overrides QF_WORKSPACE_ID)
    --strict         Treat warnings as failures (exit 1)
    --verbose        Dump response body on failure/warn
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import requests
import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

console = Console()
app = typer.Typer(add_completion=False)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class SmokeConfig:
    base_url: str
    username: str
    password: str
    workspace_id: str


def load_config(
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    workspace_id: str | None = None,
) -> SmokeConfig:
    """Load config from env vars, with optional CLI overrides."""
    cfg = SmokeConfig(
        base_url=(base_url or os.getenv("QF_BASE_URL") or "").strip(),
        username=(username or os.getenv("QF_USERNAME") or "").strip(),
        password=(password or os.getenv("QF_PASSWORD") or "").strip(),
        workspace_id=(workspace_id or os.getenv("QF_WORKSPACE_ID") or "").strip(),
    )
    missing = [k for k, v in {
        "QF_BASE_URL": cfg.base_url,
        "QF_USERNAME": cfg.username,
        "QF_PASSWORD": cfg.password,
        "QF_WORKSPACE_ID": cfg.workspace_id,
    }.items() if not v]
    if missing:
        console.print(f"[red]Missing required config: {', '.join(missing)}[/red]")
        console.print("Set these as env vars or pass as CLI flags.")
        raise SystemExit(1)
    cfg.base_url = cfg.base_url.rstrip("/")
    return cfg


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def authenticate(cfg: SmokeConfig) -> str:
    """POST to /api/v1/auth/auth and return the access token. Exits on failure."""
    url = f"{cfg.base_url}/api/v1/auth/auth"
    try:
        resp = requests.post(url, json={"username": cfg.username, "password": cfg.password}, timeout=15)
    except requests.RequestException as exc:
        console.print(f"[red]Auth request failed: {exc}[/red]")
        raise SystemExit(1)

    if resp.status_code != 200:
        body = {}
        try:
            body = resp.json()
        except Exception:
            pass
        msg = body.get("message") or f"HTTP {resp.status_code}"
        console.print(f"[red]Authentication failed: {msg}[/red]")
        raise SystemExit(1)

    data = resp.json()
    token = data.get("access_token")
    if not token:
        console.print("[red]Auth response missing access_token[/red]")
        raise SystemExit(1)
    return token


# ---------------------------------------------------------------------------
# Check result types
# ---------------------------------------------------------------------------

class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class CheckResult:
    area: str
    name: str
    status: Status
    latency_ms: int | None
    message: str
    body: dict[str, Any] = field(default_factory=dict)

    @property
    def symbol(self) -> str:
        return {"pass": "✓", "fail": "✗", "warn": "⚠", "skip": "⚠"}[self.status]

    @property
    def style(self) -> str:
        return {"pass": "green", "fail": "red", "warn": "yellow", "skip": "yellow"}[self.status]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(session: requests.Session, url: str, *, timeout: int = 10) -> tuple[int, dict[str, Any], int]:
    start = time.perf_counter()
    resp = session.get(url, timeout=timeout)
    latency = round((time.perf_counter() - start) * 1000)
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body, latency


def _post(session: requests.Session, url: str, *, json: dict[str, Any], timeout: int = 30) -> tuple[int, dict[str, Any], int]:
    start = time.perf_counter()
    resp = session.post(url, json=json, timeout=timeout)
    latency = round((time.perf_counter() - start) * 1000)
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body, latency


# ---------------------------------------------------------------------------
# Checks 1–7: Infrastructure, Users, Workspaces, Semantic, Domains
# ---------------------------------------------------------------------------

def check_healthz(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    status, body, ms = _get(session, f"{cfg.base_url}/api/v1/admin/healthz")
    if status == 200:
        return CheckResult("Infrastructure", "healthz", Status.PASS, ms, "")
    return CheckResult("Infrastructure", "healthz", Status.FAIL, ms, f"HTTP {status}", body)


def check_health_detailed(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    status, body, ms = _get(session, f"{cfg.base_url}/api/v1/admin/health/detailed")
    if status != 200:
        return CheckResult("Infrastructure", "health detailed", Status.FAIL, ms, f"HTTP {status}", body)
    overall = body.get("overall", "")
    if overall == "unhealthy":
        return CheckResult("Infrastructure", "health detailed", Status.FAIL, ms, f"overall={overall}", body)
    msg = f"note: {overall}" if overall != "healthy" else ""
    return CheckResult("Infrastructure", "health detailed", Status.PASS, ms, msg, body)


def check_users_counts(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    status, body, ms = _get(session, f"{cfg.base_url}/api/v1/users/counts")
    if status == 200 and isinstance(body, dict):
        return CheckResult("Users", "counts", Status.PASS, ms, "")
    return CheckResult("Users", "counts", Status.FAIL, ms, f"HTTP {status}", body)


def check_workspaces(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    status, body, ms = _get(session, f"{cfg.base_url}/api/v1/workspaces")
    if status != 200:
        return CheckResult("Workspaces", "list", Status.FAIL, ms, f"HTTP {status}", body)
    workspaces = body.get("workspaces") or []
    if not workspaces:
        return CheckResult("Workspaces", "list", Status.FAIL, ms, "no workspaces returned", body)
    return CheckResult("Workspaces", "list", Status.PASS, ms, f"{len(workspaces)} workspace(s)")


def _simple_get_check(area: str, name: str, session: requests.Session, url: str) -> CheckResult:
    status, body, ms = _get(session, url)
    if status == 200:
        return CheckResult(area, name, Status.PASS, ms, "")
    return CheckResult(area, name, Status.FAIL, ms, f"HTTP {status}", body)


def check_semantic_concepts(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Semantic concepts", "list", session, f"{cfg.base_url}/api/v1/semantic/concepts?limit=1")


def check_semantic_registry(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Semantic registry", "list", session, f"{cfg.base_url}/api/v1/semantic/registry?limit=1")


def check_domains(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Domains", "list", session, f"{cfg.base_url}/api/v1/domains?limit=1")


if __name__ == "__main__":
    app()
