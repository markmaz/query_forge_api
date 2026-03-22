# Smoke Test Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/smoke_test.py`, a pre-release CLI script that authenticates against a live QueryForge API and runs 16 checks across all major functional areas, printing a rich pass/fail table and exiting non-zero on failures.

**Architecture:** A single self-contained Python script using `typer` for CLI, `requests` for HTTP, and `rich` for output. Config is loaded from `.env` with CLI flag overrides. Auth uses the non-interactive `/api/v1/auth/auth` endpoint. Each check is a small function returning a `CheckResult` dataclass. The main loop runs checks sequentially, prints live status, then prints a summary table.

**Tech Stack:** Python 3.12, `requests`, `rich`, `typer`, `python-dotenv` — all already in `requirements.txt`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/smoke_test.py` | Create | Entire script: config, auth, checks, output, CLI entrypoint |
| `tests/test_smoke_test.py` | Create | Unit tests for config loading, auth, check functions, output logic |

---

## Task 1: Config loading and auth

**Files:**
- Create: `scripts/smoke_test.py` (skeleton + config + auth only)
- Create: `tests/test_smoke_test.py`

- [ ] **Step 1: Write failing tests for config and auth**

```python
# tests/test_smoke_test.py
from __future__ import annotations
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helpers — smoke_test.py lives in scripts/, not a package
# ---------------------------------------------------------------------------
import importlib.util, pathlib

_SCRIPT = pathlib.Path(__file__).parent.parent / "scripts" / "smoke_test.py"
spec = importlib.util.spec_from_file_location("smoke_test", _SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class TestLoadConfig:
    def test_reads_required_vars_from_env(self, monkeypatch):
        monkeypatch.setenv("QF_BASE_URL", "http://api.example.com")
        monkeypatch.setenv("QF_USERNAME", "tester")
        monkeypatch.setenv("QF_PASSWORD", "secret")
        monkeypatch.setenv("QF_WORKSPACE_ID", "ws-1")
        cfg = smoke.load_config()
        assert cfg.base_url == "http://api.example.com"
        assert cfg.username == "tester"
        assert cfg.password == "secret"
        assert cfg.workspace_id == "ws-1"

    def test_raises_if_required_var_missing(self, monkeypatch):
        for var in ("QF_BASE_URL", "QF_USERNAME", "QF_PASSWORD", "QF_WORKSPACE_ID"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(SystemExit):
            smoke.load_config()

    def test_cli_overrides_take_precedence(self, monkeypatch):
        monkeypatch.setenv("QF_BASE_URL", "http://from-env.example.com")
        monkeypatch.setenv("QF_USERNAME", "env-user")
        monkeypatch.setenv("QF_PASSWORD", "env-pass")
        monkeypatch.setenv("QF_WORKSPACE_ID", "ws-env")
        cfg = smoke.load_config(
            base_url="http://from-cli.example.com",
            username="cli-user",
        )
        assert cfg.base_url == "http://from-cli.example.com"
        assert cfg.username == "cli-user"
        # non-overridden fields still come from env
        assert cfg.password == "env-pass"


class TestAuthenticate:
    def _cfg(self):
        return smoke.SmokeConfig(
            base_url="http://api.example.com",
            username="tester",
            password="secret",
            workspace_id="ws-1",
        )

    def test_returns_token_on_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "tok-abc"}
        with patch("requests.post", return_value=mock_resp):
            token = smoke.authenticate(self._cfg())
        assert token == "tok-abc"

    def test_exits_on_401(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "Invalid username or password"}
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(SystemExit):
                smoke.authenticate(self._cfg())

    def test_posts_to_correct_endpoint(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "tok-xyz"}
        with patch("requests.post", return_value=mock_resp) as mock_post:
            smoke.authenticate(self._cfg())
        url = mock_post.call_args[0][0]
        assert url.endswith("/api/v1/auth/auth")
        payload = mock_post.call_args[1]["json"]
        assert payload["username"] == "tester"
        assert payload["password"] == "secret"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py -v 2>&1 | tail -15
```

Expected: `AttributeError` — `spec_from_file_location` returns `None` when the file doesn't exist, and `module_from_spec(None)` raises `AttributeError`.

- [ ] **Step 3: Implement config + auth skeleton in `scripts/smoke_test.py`**

```python
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
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import requests
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

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

    token = resp.json().get("access_token")
    if not token:
        console.print("[red]Auth response missing access_token[/red]")
        raise SystemExit(1)
    return token
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestLoadConfig tests/test_smoke_test.py::TestAuthenticate -v 2>&1 | tail -15
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
git add scripts/smoke_test.py tests/test_smoke_test.py
git commit -m "feat: smoke test script skeleton — config and auth"
```

---

## Task 2: Check result types and HTTP helpers

**Files:**
- Modify: `scripts/smoke_test.py` — add `Status`, `CheckResult`, `_get()`, `_post()`
- Modify: `tests/test_smoke_test.py` — add `TestHttpHelpers`

- [ ] **Step 1: Write failing tests for HTTP helpers**

Add to `tests/test_smoke_test.py`:

```python
class TestHttpHelpers:
    def _session(self):
        s = requests.Session()
        s.headers.update({"Authorization": "Bearer tok", "X-Workspace-Id": "ws-1"})
        return s

    def test_get_returns_status_body_latency(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        with patch.object(requests.Session, "get", return_value=mock_resp):
            status, body, latency = smoke._get(self._session(), "http://x/path")
        assert status == 200
        assert body == {"ok": True}
        assert isinstance(latency, int) and latency >= 0

    def test_get_returns_empty_body_on_json_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        with patch.object(requests.Session, "get", return_value=mock_resp):
            status, body, latency = smoke._get(self._session(), "http://x/path")
        assert status == 200
        assert body == {}

    def test_post_returns_status_body_latency(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "ok"}
        with patch.object(requests.Session, "post", return_value=mock_resp):
            status, body, latency = smoke._post(self._session(), "http://x/path", json={"q": "x"})
        assert status == 200
        assert body["result"] == "ok"

    def test_check_result_is_fail_on_bad_status(self):
        r = smoke.CheckResult(
            area="Infra", name="healthz",
            status=smoke.Status.FAIL, latency_ms=12, message="503"
        )
        assert r.status == smoke.Status.FAIL
        assert r.latency_ms == 12
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestHttpHelpers -v 2>&1 | tail -10
```

Expected: `AttributeError` — `Status`, `CheckResult`, `_get`, `_post` not defined yet.

- [ ] **Step 3: Add Status, CheckResult, _get, _post to `scripts/smoke_test.py`**

Add after the `authenticate` function:

```python
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

def _get(session: requests.Session, url: str, *, timeout: int = 10) -> tuple[int, dict, int]:
    start = time.perf_counter()
    resp = session.get(url, timeout=timeout)
    latency = int((time.perf_counter() - start) * 1000)
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body, latency


def _post(session: requests.Session, url: str, *, json: dict, timeout: int = 30) -> tuple[int, dict, int]:
    start = time.perf_counter()
    resp = session.post(url, json=json, timeout=timeout)
    latency = int((time.perf_counter() - start) * 1000)
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body, latency
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestHttpHelpers -v 2>&1 | tail -10
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.py tests/test_smoke_test.py
git commit -m "feat: smoke test — CheckResult types and HTTP helpers"
```

---

## Task 3: Infrastructure and core data checks (#1–#7)

**Files:**
- Modify: `scripts/smoke_test.py` — add checks 1–7
- Modify: `tests/test_smoke_test.py` — add `TestChecks1To7`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_smoke_test.py`:

```python
import requests as _requests

def _session(cfg=None):
    if cfg is None:
        cfg = smoke.SmokeConfig("http://api", "u", "p", "ws-1")
    s = _requests.Session()
    s.headers.update({"Authorization": "Bearer tok", "X-Workspace-Id": cfg.workspace_id})
    return s, cfg


class TestChecks1To7:
    def _ok(self, body=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = body or {}
        return m

    def _err(self, code=500):
        m = MagicMock()
        m.status_code = code
        m.json.return_value = {"error": "fail"}
        return m

    def test_check_healthz_pass(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._ok()):
            result = smoke.check_healthz(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_healthz_fail(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._err(503)):
            result = smoke.check_healthz(session, cfg)
        assert result.status == smoke.Status.FAIL

    def test_check_health_detailed_pass(self):
        session, cfg = _session()
        body = {"overall": "healthy", "checks": {}}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_health_detailed(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_health_detailed_fail_when_unhealthy(self):
        session, cfg = _session()
        body = {"overall": "unhealthy", "checks": {}}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_health_detailed(session, cfg)
        assert result.status == smoke.Status.FAIL

    def test_check_health_detailed_pass_when_degraded(self):
        # "degraded" is not "unhealthy" — should still pass
        session, cfg = _session()
        body = {"overall": "degraded", "checks": {}}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_health_detailed(session, cfg)
        assert result.status == smoke.Status.PASS
        assert "degraded" in result.message

    def test_check_users_counts_pass(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._ok({"total": 5})):
            result = smoke.check_users_counts(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_workspaces_pass(self):
        session, cfg = _session()
        body = {"workspaces": [{"id": "ws-1"}]}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_workspaces(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_workspaces_fail_when_empty(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._ok({"workspaces": []})):
            result = smoke.check_workspaces(session, cfg)
        assert result.status == smoke.Status.FAIL

    def test_simple_checks_pass_on_200(self):
        # checks 5, 6, 7 just need HTTP 200
        for fn in (smoke.check_semantic_concepts, smoke.check_semantic_registry, smoke.check_domains):
            session, cfg = _session()
            with patch.object(session, "get", return_value=self._ok()):
                result = fn(session, cfg)
            assert result.status == smoke.Status.PASS, f"{fn.__name__} should pass on 200"

    def test_simple_checks_fail_on_non_200(self):
        for fn in (smoke.check_semantic_concepts, smoke.check_semantic_registry, smoke.check_domains):
            session, cfg = _session()
            with patch.object(session, "get", return_value=self._err()):
                result = fn(session, cfg)
            assert result.status == smoke.Status.FAIL, f"{fn.__name__} should fail on 500"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestChecks1To7 -v 2>&1 | tail -15
```

Expected: `AttributeError` — check functions not defined yet.

- [ ] **Step 3: Add checks 1–7 to `scripts/smoke_test.py`**

Add after `_post`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestChecks1To7 -v 2>&1 | tail -15
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.py tests/test_smoke_test.py
git commit -m "feat: smoke test — infrastructure and core data checks 1-7"
```

---

## Task 4: Planner and query execution (#8–#9)

**Files:**
- Modify: `scripts/smoke_test.py` — add `check_planner`, `check_query_execution`
- Modify: `tests/test_smoke_test.py` — add `TestChecks8And9`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_smoke_test.py`:

```python
class TestChecks8And9:
    def _ok(self, body=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = body or {}
        return m

    def _err(self, code=500):
        m = MagicMock()
        m.status_code = code
        m.json.return_value = {}
        return m

    def test_check_planner_pass_returns_sql_json(self):
        session, cfg = _session()
        body = {"sql_json": {"version": 1, "domainId": 5}, "trace_id": "abc"}
        with patch.object(session, "post", return_value=self._ok(body)):
            result, sql_json = smoke.check_planner(session, cfg)
        assert result.status == smoke.Status.PASS
        assert sql_json == {"version": 1, "domainId": 5}

    def test_check_planner_fail_on_500(self):
        session, cfg = _session()
        with patch.object(session, "post", return_value=self._err(500)):
            result, sql_json = smoke.check_planner(session, cfg)
        assert result.status == smoke.Status.FAIL
        assert sql_json is None

    def test_check_planner_fail_when_no_sql_json_in_response(self):
        session, cfg = _session()
        with patch.object(session, "post", return_value=self._ok({"error": "no domain"})):
            result, sql_json = smoke.check_planner(session, cfg)
        assert result.status == smoke.Status.FAIL
        assert sql_json is None

    def test_check_query_execution_skipped_when_no_sql_json(self):
        session, cfg = _session()
        result = smoke.check_query_execution(session, cfg, sql_json=None)
        assert result.status == smoke.Status.SKIP
        assert "planner failed" in result.message

    def test_check_query_execution_warn_on_500(self):
        session, cfg = _session()
        with patch.object(session, "post", return_value=self._err(500)):
            result = smoke.check_query_execution(session, cfg, sql_json={"version": 1})
        assert result.status == smoke.Status.WARN

    def test_check_query_execution_pass_on_200(self):
        session, cfg = _session()
        body = {"rows": [], "total": 0}
        with patch.object(session, "post", return_value=self._ok(body)):
            result = smoke.check_query_execution(session, cfg, sql_json={"version": 1})
        assert result.status == smoke.Status.PASS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestChecks8And9 -v 2>&1 | tail -10
```

Expected: `AttributeError` — check functions not defined.

- [ ] **Step 3: Add checks 8–9 to `scripts/smoke_test.py`**

```python
# ---------------------------------------------------------------------------
# Checks 8–9: Planner and Query Execution
# ---------------------------------------------------------------------------

def check_planner(session: requests.Session, cfg: SmokeConfig) -> tuple[CheckResult, dict | None]:
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
    session: requests.Session, cfg: SmokeConfig, *, sql_json: dict | None
) -> CheckResult:
    if sql_json is None:
        return CheckResult("Query execution", "run", Status.SKIP, None, "skipped (planner failed)")
    status, body, ms = _post(session, f"{cfg.base_url}/api/v1/query/", json=sql_json)
    if status == 200:
        return CheckResult("Query execution", "run", Status.PASS, ms, "")
    # Warn rather than hard-fail — datasource may be unavailable in some environments
    return CheckResult("Query execution", "run", Status.WARN, ms, f"HTTP {status}", body)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestChecks8And9 -v 2>&1 | tail -10
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.py tests/test_smoke_test.py
git commit -m "feat: smoke test — planner and query execution checks 8-9"
```

---

## Task 5: Remaining checks (#10–#16)

**Files:**
- Modify: `scripts/smoke_test.py` — add checks 10–16
- Modify: `tests/test_smoke_test.py` — add `TestChecks10To16`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_smoke_test.py`:

```python
class TestChecks10To16:
    def _ok(self, body=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = body or {}
        return m

    def _err(self):
        m = MagicMock()
        m.status_code = 500
        m.json.return_value = {}
        return m

    def test_all_simple_checks_pass_on_200(self):
        fns = [
            smoke.check_saved_queries,
            smoke.check_skills,
            smoke.check_skills_scheduler,
            smoke.check_ai_health,
            smoke.check_datasources,
            smoke.check_pipeline_profiles,
        ]
        for fn in fns:
            session, cfg = _session()
            with patch.object(session, "get", return_value=self._ok()):
                result = fn(session, cfg)
            assert result.status == smoke.Status.PASS, f"{fn.__name__} should pass on 200"

    def test_all_simple_checks_fail_on_non_200(self):
        fns = [
            smoke.check_saved_queries,
            smoke.check_skills,
            smoke.check_skills_scheduler,
            smoke.check_destinations,
            smoke.check_ai_health,
            smoke.check_datasources,
            smoke.check_pipeline_profiles,
        ]
        for fn in fns:
            session, cfg = _session()
            with patch.object(session, "get", return_value=self._err()):
                result = fn(session, cfg)
            assert result.status == smoke.Status.FAIL, f"{fn.__name__} should fail on 500"

    def test_check_destinations_uses_workspace_id_in_url(self):
        session, cfg = _session()
        captured_urls = []
        orig_get = session.get
        def capturing_get(url, **kwargs):
            captured_urls.append(url)
            return self._ok()
        with patch.object(session, "get", side_effect=capturing_get):
            smoke.check_destinations(session, cfg)
        assert cfg.workspace_id in captured_urls[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestChecks10To16 -v 2>&1 | tail -10
```

Expected: `AttributeError` — check functions not defined.

- [ ] **Step 3: Add checks 10–16 to `scripts/smoke_test.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestChecks10To16 -v 2>&1 | tail -10
```

Expected: 3 tests pass (covering all 7 check functions).

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.py tests/test_smoke_test.py
git commit -m "feat: smoke test — remaining checks 10-16"
```

---

## Task 6: Rich output and main entrypoint

**Files:**
- Modify: `scripts/smoke_test.py` — add `print_result`, `print_summary`, `main`
- Modify: `tests/test_smoke_test.py` — add `TestSummaryLogic`

- [ ] **Step 1: Write failing tests for summary exit logic**

Add to `tests/test_smoke_test.py`:

```python
class TestSummaryLogic:
    def _result(self, status):
        return smoke.CheckResult("Area", "name", smoke.Status(status), 10, "msg")

    def test_exit_code_0_when_all_pass(self):
        results = [self._result("pass")] * 5
        code = smoke.compute_exit_code(results, strict=False)
        assert code == 0

    def test_exit_code_1_when_any_fail(self):
        results = [self._result("pass"), self._result("fail"), self._result("pass")]
        code = smoke.compute_exit_code(results, strict=False)
        assert code == 1

    def test_exit_code_0_for_warn_without_strict(self):
        results = [self._result("pass"), self._result("warn")]
        code = smoke.compute_exit_code(results, strict=False)
        assert code == 0

    def test_exit_code_1_for_warn_with_strict(self):
        results = [self._result("pass"), self._result("warn")]
        code = smoke.compute_exit_code(results, strict=True)
        assert code == 1

    def test_exit_code_0_for_skip_without_strict(self):
        results = [self._result("pass"), self._result("skip")]
        code = smoke.compute_exit_code(results, strict=False)
        assert code == 0

    def test_exit_code_0_for_skip_with_strict(self):
        # skips are structural (dependency chain), not warnings — strict does not escalate them
        results = [self._result("pass"), self._result("skip")]
        code = smoke.compute_exit_code(results, strict=True)
        assert code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py::TestSummaryLogic -v 2>&1 | tail -10
```

Expected: `AttributeError` — `compute_exit_code` not defined.

- [ ] **Step 3: Add output functions and main to `scripts/smoke_test.py`**

```python
# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_CHECKS: list[tuple[str, Any]] = []  # populated in run_all()


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
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py -v 2>&1 | tail -20
```

Expected: all tests pass (approximately 30 total).

- [ ] **Step 5: Verify the script is importable and --help works**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 scripts/smoke_test.py --help
```

Expected: typer help output showing all options.

- [ ] **Step 6: Commit**

```bash
git add scripts/smoke_test.py tests/test_smoke_test.py
git commit -m "feat: smoke test — output, exit logic, and main entrypoint"
```

---

## Task 7: Full test suite verification

**Files:**
- No new files — just verification

- [ ] **Step 1: Run the full smoke test unit suite**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest tests/test_smoke_test.py -v 2>&1 | tail -10
```

Expected: all tests pass, 0 failures.

- [ ] **Step 2: Run the full backend test suite to confirm no regressions**

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api"
python3 -m pytest -q 2>&1 | tail -5
```

Expected: all existing tests still pass.

- [ ] **Step 3: Verify the script syntax and --help one more time**

```bash
python3 scripts/smoke_test.py --help
```

Expected: clean help output, no import errors.

- [ ] **Step 4: Final commit**

```bash
git add scripts/smoke_test.py tests/test_smoke_test.py
git commit -m "feat: smoke test script complete — 16 checks across all functional areas"
```

---

## Running the smoke test

After implementation, run against a live environment:

```bash
# From .env (set QF_BASE_URL, QF_USERNAME, QF_PASSWORD, QF_WORKSPACE_ID)
python3 scripts/smoke_test.py

# With CLI overrides
python3 scripts/smoke_test.py --base-url http://localhost:5000 --workspace-id ws_abc123

# Strict mode (warnings fail the run)
python3 scripts/smoke_test.py --strict

# Verbose (dump response bodies on failure)
python3 scripts/smoke_test.py --verbose
```
