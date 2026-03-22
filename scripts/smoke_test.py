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


# ---------------------------------------------------------------------------
# Checks 8–9: Planner and Query Execution
# ---------------------------------------------------------------------------

def check_planner(session: requests.Session, cfg: SmokeConfig) -> tuple[CheckResult, dict[str, Any] | None]:
    """Returns (CheckResult, sql_json | None). sql_json is passed to check_query_execution."""
    payload = {"prompt": "List all records", "workspace_id": cfg.workspace_id}
    status, body, ms = _post(session, f"{cfg.base_url}/api/v1/planner/plan_domain", json=payload)
    if status != 200:
        return CheckResult("Planner", "plan_domain", Status.FAIL, ms, f"HTTP {status}", body), None
    sql_json = body.get("sql_json")
    if not isinstance(sql_json, dict):
        return CheckResult("Planner", "plan_domain", Status.FAIL, ms, "response missing sql_json", body), None
    return CheckResult("Planner", "plan_domain", Status.PASS, ms, ""), sql_json


def check_query_execution(
    session: requests.Session, cfg: SmokeConfig, *, sql_json: dict[str, Any] | None
) -> CheckResult:
    if sql_json is None:
        return CheckResult("Query execution", "run", Status.SKIP, None, "skipped (planner failed)")
    status, body, ms = _post(session, f"{cfg.base_url}/api/v1/query/", json=sql_json)
    if status == 200:
        return CheckResult("Query execution", "run", Status.PASS, ms, "")
    # Warn rather than hard-fail — datasource may be unavailable in some environments
    return CheckResult("Query execution", "run", Status.WARN, ms, f"HTTP {status}", body)


# ---------------------------------------------------------------------------
# Checks 10–16: Saved Queries, Skills, AI, Ingestion, Vector Admin
# ---------------------------------------------------------------------------

def check_saved_queries(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Saved queries", "list", session, f"{cfg.base_url}/api/v1/query-tree/recent")


def check_skills(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Skills", "list", session, f"{cfg.base_url}/api/v1/skills")


def check_skills_scheduler(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Skills scheduler", "status", session, f"{cfg.base_url}/api/v1/skills/scheduler/status")


def check_destinations(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check(
        "Destinations", "list", session,
        f"{cfg.base_url}/api/v1/workspaces/{cfg.workspace_id}/destinations"
    )


def check_ai_health(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("AI", "health", session, f"{cfg.base_url}/api/v1/ai/health")


def check_datasources(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Ingestion", "datasources", session, f"{cfg.base_url}/api/v1/datasources")


def check_pipeline_profiles(session: requests.Session, cfg: SmokeConfig) -> CheckResult:
    return _simple_get_check("Vector admin", "status", session, f"{cfg.base_url}/api/v1/admin/pipeline-profiles?limit=1")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _latency_str(ms: int | None) -> str:
    return f"{ms}ms" if ms is not None else "—"


def print_header(cfg: SmokeConfig) -> None:
    console.print()
    console.print(f"[bold]QueryForge Smoke Test[/bold] — {cfg.base_url}  (workspace: {cfg.workspace_id})")
    console.print("─" * 70)


def print_result(result: CheckResult, verbose: bool = False) -> None:
    label = f"{result.area} / {result.name}"
    latency = _latency_str(result.latency_ms)
    note = f"   {result.message}" if result.message else ""
    console.print(
        f"  [{result.style}]{result.symbol}[/{result.style}]  "
        f"{label:<42} {latency:>6}{note}"
    )
    if verbose and result.status in (Status.FAIL, Status.WARN) and result.body:
        import json
        console.print(f"    [dim]{json.dumps(result.body, indent=2)[:500]}[/dim]")


def print_summary(results: list[CheckResult], exit_code: int) -> None:
    console.print("─" * 70)
    passed = sum(1 for r in results if r.status == Status.PASS)
    failed = sum(1 for r in results if r.status == Status.FAIL)
    warned = sum(1 for r in results if r.status == Status.WARN)
    skipped = sum(1 for r in results if r.status == Status.SKIP)
    parts = [f"[bold]{len(results)} checks[/bold]"]
    parts.append(f"[green]{passed} passed[/green]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    if warned:
        parts.append(f"[yellow]{warned} warned[/yellow]")
    if skipped:
        parts.append(f"[yellow]{skipped} skipped[/yellow]")
    console.print("  " + "   ".join(parts))
    color = "green" if exit_code == 0 else "red"
    console.print(f"  [{color}]Exit code {exit_code}[/{color}]")
    console.print()


def compute_exit_code(results: list[CheckResult], *, strict: bool) -> int:
    if any(r.status == Status.FAIL for r in results):
        return 1
    if strict and any(r.status == Status.WARN for r in results):
        return 1
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all(session: requests.Session, cfg: SmokeConfig, *, verbose: bool, strict: bool) -> int:
    print_header(cfg)
    results: list[CheckResult] = []

    def run(fn, *args, **kwargs):
        r = fn(session, cfg, *args, **kwargs)
        print_result(r, verbose=verbose)
        results.append(r)
        return r

    run(check_healthz)
    run(check_health_detailed)
    run(check_users_counts)
    run(check_workspaces)
    run(check_semantic_concepts)
    run(check_semantic_registry)
    run(check_domains)
    planner_result, sql_json = check_planner(session, cfg)
    print_result(planner_result, verbose=verbose)
    results.append(planner_result)
    run(check_query_execution, sql_json=sql_json if planner_result.status == Status.PASS else None)
    run(check_saved_queries)
    run(check_skills)
    run(check_skills_scheduler)
    run(check_destinations)
    run(check_ai_health)
    run(check_datasources)
    run(check_pipeline_profiles)

    exit_code = compute_exit_code(results, strict=strict)
    print_summary(results, exit_code)
    return exit_code


@app.command()
def main(
    base_url: str = typer.Option(None, "--base-url", envvar="QF_BASE_URL", help="API root URL"),
    username: str = typer.Option(None, "--username", envvar="QF_USERNAME", help="Login username"),
    password: str = typer.Option(None, "--password", envvar="QF_PASSWORD", help="Login password"),
    workspace_id: str = typer.Option(None, "--workspace-id", envvar="QF_WORKSPACE_ID", help="Workspace ID"),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as failures"),
    verbose: bool = typer.Option(False, "--verbose", help="Dump response body on failure"),
) -> None:
    cfg = load_config(base_url=base_url, username=username, password=password, workspace_id=workspace_id)
    token = authenticate(cfg)

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "X-Workspace-Id": cfg.workspace_id,
        "Content-Type": "application/json",
    })

    exit_code = run_all(session, cfg, verbose=verbose, strict=strict)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    app()
