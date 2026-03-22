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
from dataclasses import dataclass

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


if __name__ == "__main__":
    app()
