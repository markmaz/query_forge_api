# Smoke Test Script Design

**Date:** 2026-03-22
**Project:** query-forge-api
**Location:** `scripts/smoke_test.py`

---

## Purpose

A pre-release sanity script that authenticates against a live QueryForge API instance and exercises every major functional area with a single HTTP call per area. Produces a clear pass/fail/warn table and exits non-zero on hard failures. Intended to be run by a developer before every release against the target environment.

---

## Config & Auth

Configuration is read from the project `.env` file (via `python-dotenv`) with CLI flag overrides (via `typer`).

Required variables:

| Variable | CLI flag | Description |
|---|---|---|
| `QF_BASE_URL` | `--base-url` | API root, e.g. `http://localhost:5000` |
| `QF_USERNAME` | `--username` | Smoke test user login |
| `QF_PASSWORD` | `--password` | Smoke test user password |
| `QF_WORKSPACE_ID` | `--workspace-id` | Workspace to run checks against |

On startup the script calls `POST /api/v1/auth/auth` (non-interactive, no OTP). Auth failure is **fatal** — the script exits immediately with a clear error message rather than running checks that will all fail with 401.

The returned `access_token` is stored and injected as `Authorization: Bearer <token>` on all subsequent requests. `QF_WORKSPACE_ID` from config is injected as `X-Workspace-Id`. The `workspace_id` field in the auth response is ignored — the config value is authoritative.

**Note:** The smoke test user account must have the admin role. Checks #2, #3, #4, #16 call admin-gated endpoints and will return 403 with a non-admin token.

---

## Check Catalog

Checks run sequentially in this order. Each check makes exactly one HTTP call and asserts a minimal condition.

| # | Area | Endpoint | Pass condition | Failure mode |
|---|---|---|---|---|
| 1 | Infrastructure | `GET /admin/healthz` | HTTP 200 | hard fail |
| 2 | Infrastructure | `GET /admin/health/detailed` | 200, `overall` ≠ `unhealthy` | hard fail |
| 3 | Users | `GET /users/counts` | 200, response is a dict | hard fail |
| 4 | Workspaces | `GET /workspaces` | 200, ≥ 1 workspace | hard fail |
| 5 | Semantic concepts | `GET /semantic/concepts?limit=1` | 200 | hard fail |
| 6 | Semantic registry | `GET /semantic/registry?limit=1` | 200 | hard fail |
| 7 | Domains | `GET /domains?limit=1` | 200 | hard fail |
| 8 | Planner | `POST /planner/plan_domain` | 200, response contains `sql_json` key | hard fail |
| 9 | Query execution | `POST /query/` with body = `response["sql_json"]` from #8 | 200 or non-500 | **warn** |
| 10 | Saved queries | `GET /query-tree/recent` | 200 | hard fail |
| 11 | Skills | `GET /skills` | 200 | hard fail |
| 12 | Skills scheduler | `GET /skills/scheduler/status` | 200 | hard fail |
| 13 | Destinations | `GET /workspaces/<QF_WORKSPACE_ID>/destinations` | 200 | hard fail |
| 14 | AI health | `GET /ai/health` | 200 | hard fail |
| 15 | Ingestion | `GET /datasources` | 200 | hard fail |
| 16 | Vector admin | `GET /admin/pipeline-profiles?limit=1` | 200 | hard fail |

**Dependency skipping:** check #9 (query execution) is automatically skipped if check #8 (planner) failed, since there is no `sql_json` to pass as the body. Check #9 is the only skip dependency — all other checks are independent.

The planner check uses a fixed minimal prompt (`"List all records"`) with `workspace_id` from config and no domain specified — just enough to confirm the planning pipeline responds without a 500.

---

## Output

The script prints a live status line as each check runs, then a final summary table.

```
QueryForge Smoke Test — http://localhost:5000  (workspace: ws_abc123)
──────────────────────────────────────────────────────────────────────
  ✓  Infrastructure / healthz               12ms
  ✓  Infrastructure / health detailed       45ms   note: vllm degraded
  ✓  Users / counts                         23ms
  ✓  Workspaces / list                      31ms
  ✓  Semantic concepts / list               18ms
  ✓  Semantic registry / list               22ms
  ✓  Domains / list                         19ms
  ✗  Planner / plan_domain                 402ms   500 Internal Server Error
  ⚠  Query execution / run                   —     skipped (planner failed)
  ✓  Saved queries / list                   17ms
  ✓  Skills / list                          14ms
  ✓  Skills scheduler / status              11ms
  ✓  Destinations / list                    16ms
  ✓  AI / health                            88ms
  ✓  Ingestion / datasources                21ms
  ✓  Vector admin / status                  33ms
──────────────────────────────────────────────────────────────────────
  16 checks   14 passed   1 failed   1 skipped
  Exit code 1
```

**Symbols:**
- `✓` — passed
- `✗` — hard fail
- `⚠` — warn (soft issue, does not fail exit code by default)

**Flags:**
- `--strict` — treats warnings as hard failures (exit 1)
- `--verbose` — dumps full response body for any failed or warned check

**Exit codes:**
- `0` — all hard checks passed
- `1` — one or more hard checks failed (or warnings present with `--strict`)

---

## File Layout

```
scripts/
  smoke_test.py        # single self-contained script
```

No new dependencies — uses `requests`, `rich`, `typer`, and `python-dotenv`, all already in `requirements.txt`.

---

## Non-Goals

- Does not create, modify, or delete any data
- Does not test every endpoint — one representative call per functional area
- Does not replace unit tests or Playwright E2E tests
- Does not test Databricks/Snowflake datasource connectivity directly
