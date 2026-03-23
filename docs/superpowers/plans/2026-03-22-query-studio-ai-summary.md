# Query Studio AI Result Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After Run Preview completes in Query Studio, auto-generate an AI summary of result rows and display it in a collapsible section above the data table, with a session toggle to disable it.

**Architecture:** New stateless `POST /api/v1/query-studio/summarize` endpoint accepts raw rows from the frontend, applies a row cap, calls the shared `analysis_utils` LLM pipeline, and returns `{narrative, highlights, comparison, capped}`. Frontend hook `useResultSummary` manages fetching via TanStack React Query; `ResultSummary` component renders the collapsible section. The toggle controls CSS visibility only — the component stays mounted.

**Tech Stack:** Python Flask-RESTX (backend), React 19 + TypeScript, TanStack React Query 5, Bootstrap 5 + Reactstrap (frontend)

---

## File Manifest

### New — Backend
| File | Purpose |
|------|---------|
| `app/exceptions/llm_unavailable_error.py` | New exception class `LLMUnavailableError` |
| `app/services/query_studio_summary_service.py` | `generate_preview_summary()` — row cap + LLM call |
| `app/routes/query_studio_summary_routes.py` | `POST /summarize` Flask-RESTX namespace |
| `app/features/query_studio/` directory | Feature registrar |
| `app/features/query_studio/__init__.py` | `register(api)` registrar |
| `tests/services/test_query_studio_summary_service.py` | Service unit tests |
| `tests/routes/test_query_studio_summary_routes.py` | Route integration tests |

### Modify — Backend
| File | Change |
|------|--------|
| `app/exceptions/forge_error.py` | No change — `LLMUnavailableError` is a sibling exception |
| `app/features/__init__.py` | Import and register `query_studio` feature |
| `version.json` | Bump `0.2.0` → `0.3.0` |

### New — Frontend
| File | Purpose |
|------|---------|
| `src/features/query-forge/ui/components/ResultSummary/ResultSummary.tsx` | Collapsible AI summary section |
| `src/features/query-forge/ui/components/ResultSummary/ResultSummary.test.tsx` | Component tests |
| `src/features/query-forge/ui/hooks/useResultSummary.ts` | TanStack React Query data-fetching hook |
| `src/features/query-forge/ui/hooks/useResultSummary.test.ts` | Hook tests |

> **Path note:** The spec's file manifest lists paths as `src/features/query-forge/components/` and `src/features/query-forge/hooks/`. The actual codebase structure uses `src/features/query-forge/ui/components/` and `src/features/query-forge/ui/hooks/` (consistent with all other query-forge components like `PreviewSection.tsx`, `FiltersSection.tsx`, etc.). This plan uses the real on-disk paths.

### Modify — Frontend
| File | Change |
|------|--------|
| `src/shared/services/queryStudioAdminApi.ts` | Add `summarizePreview()` API function + types |
| `src/shared/services/api.ts` | Add `"/query-studio"` to `WORKSPACE_SCOPED_PREFIXES` |
| `src/features/query-forge/ui/components/PreviewSection.tsx` | Wire up toggle, hook, and `<ResultSummary>` |
| `package.json` | Bump version `0.2.0` → `0.3.0` |

---

## Task 1: Backend — `LLMUnavailableError` exception

**Files:**
- Create: `query-forge-api/app/exceptions/llm_unavailable_error.py`

- [ ] **Step 1: Write the failing test**

Create `tests/exceptions/test_llm_unavailable_error.py`:

```python
from __future__ import annotations

def test_import_and_raise():
    from app.exceptions.llm_unavailable_error import LLMUnavailableError
    err = LLMUnavailableError("no llm configured")
    assert isinstance(err, Exception)
    assert "no llm configured" in str(err)

def test_is_not_forge_error():
    from app.exceptions.llm_unavailable_error import LLMUnavailableError
    from app.exceptions.forge_error import ForgeError
    assert not issubclass(LLMUnavailableError, ForgeError)
```

- [ ] **Step 1b: Run test to verify it fails**

```bash
cd query-forge-api && python -m pytest tests/exceptions/test_llm_unavailable_error.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` — module doesn't exist.

- [ ] **Step 2: Create the exception class**

Create `app/exceptions/llm_unavailable_error.py`:

```python
from __future__ import annotations


class LLMUnavailableError(Exception):
    """Raised when no LLM is configured for the workspace."""
    pass
```

- [ ] **Step 3: Run test to verify it passes**

```bash
cd query-forge-api && python -m pytest tests/exceptions/test_llm_unavailable_error.py -v
```
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add query-forge-api/app/exceptions/llm_unavailable_error.py \
        query-forge-api/tests/exceptions/test_llm_unavailable_error.py
git commit -m "feat: add LLMUnavailableError exception for query studio summary"
```

---

## Task 2: Backend — Summary service

**Files:**
- Create: `query-forge-api/app/services/query_studio_summary_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/test_query_studio_summary_service.py`:

```python
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

import app.services.query_studio_summary_service as svc_module
from app.services.query_studio_summary_service import generate_preview_summary
from app.exceptions.llm_unavailable_error import LLMUnavailableError


ROWS_10 = [{"col": str(i)} for i in range(10)]
ROWS_150 = [{"col": str(i)} for i in range(150)]

LLM_RESPONSE = {
    "narrative": "Test narrative.",
    "highlights": ["highlight 1", "highlight 2"],
    "comparison": None,
}


def _patch_llm(result=None, side_effect=None):
    """Patch call_analysis_llm and both prompt builders."""
    return [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(
            svc_module, "call_analysis_llm",
            return_value=result or LLM_RESPONSE,
            side_effect=side_effect,
        ),
    ]


def _apply_patches(patches):
    for p in patches:
        p.start()
    return patches


def _stop_patches(patches):
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_returns_normalized_fields():
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "My Query", ["col"], ROWS_10)
        assert result == {
            "narrative": "Test narrative.",
            "highlights": ["highlight 1", "highlight 2"],
            "comparison": None,
            "capped": False,
        }
    finally:
        _stop_patches(patches)


def test_capped_false_when_rows_under_max():
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["capped"] is False
    finally:
        _stop_patches(patches)


def test_capped_true_when_rows_exceed_max(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_150)
        assert result["capped"] is True
    finally:
        _stop_patches(patches)


def test_only_max_rows_sent_to_llm(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"), \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr") as mock_user_prompt, \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_150)
        call_kwargs = mock_user_prompt.call_args
        rows_passed = call_kwargs.kwargs.get("rows") or call_kwargs.args[3] if call_kwargs.args else call_kwargs.kwargs["rows"]
        assert len(rows_passed) == 100


def test_original_row_count_passed_to_user_prompt(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"), \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr") as mock_user_prompt, \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_150)
        call_kwargs = mock_user_prompt.call_args
        row_count = call_kwargs.kwargs.get("row_count") if call_kwargs.kwargs else call_kwargs.args[2]
        assert row_count == 150


def test_cap_disclaimer_appended_to_prompt_hint(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys") as mock_sys, \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"), \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_150, prompt_hint="focus on revenue")
        hint_used = mock_sys.call_args.kwargs.get("hint") or mock_sys.call_args.args[0]
        assert "100 rows of 150 total" in hint_used
        assert "focus on revenue" in hint_used


def test_include_comparison_false_passed_to_system_prompt():
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys") as mock_sys, \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"), \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert mock_sys.call_args.kwargs.get("include_comparison") is False


def test_previous_highlights_and_run_date_are_none():
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"), \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr") as mock_user, \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        kwargs = mock_user.call_args.kwargs
        assert kwargs.get("previous_highlights") is None
        assert kwargs.get("previous_run_date") is None


def test_empty_rows_accepted_capped_false():
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "Q", [], [])
        assert result["capped"] is False
    finally:
        _stop_patches(patches)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_llm_unavailable_raises_llm_unavailable_error_404():
    """ForgeError 404 = no LLM config found → LLMUnavailableError."""
    from app.exceptions.forge_error import ForgeError
    patches = [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(svc_module, "call_analysis_llm", side_effect=ForgeError("No LLM", status_code=404)),
    ]
    _apply_patches(patches)
    try:
        with pytest.raises(LLMUnavailableError):
            generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
    finally:
        _stop_patches(patches)


def test_llm_unavailable_raises_llm_unavailable_error_400():
    """ForgeError 400 = LLM misconfigured (no model/endpoint/key) → LLMUnavailableError."""
    from app.exceptions.forge_error import ForgeError
    patches = [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(svc_module, "call_analysis_llm", side_effect=ForgeError("LLM model_name is not configured", status_code=400)),
    ]
    _apply_patches(patches)
    try:
        with pytest.raises(LLMUnavailableError):
            generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
    finally:
        _stop_patches(patches)


def test_llm_failure_propagates():
    patches = [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(svc_module, "call_analysis_llm", side_effect=RuntimeError("LLM exploded")),
    ]
    _apply_patches(patches)
    try:
        with pytest.raises(RuntimeError, match="LLM exploded"):
            generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
    finally:
        _stop_patches(patches)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_normalizes_missing_highlights_to_empty_list():
    llm_resp = {"narrative": "text", "comparison": None}  # no highlights key
    patches = _apply_patches(_patch_llm(result=llm_resp))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["highlights"] == []
    finally:
        _stop_patches(patches)


def test_normalizes_none_highlights_to_empty_list():
    llm_resp = {"narrative": "text", "highlights": None, "comparison": None}
    patches = _apply_patches(_patch_llm(result=llm_resp))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["highlights"] == []
    finally:
        _stop_patches(patches)


def test_normalizes_missing_narrative_to_empty_string():
    llm_resp = {"highlights": ["h1"], "comparison": None}  # no narrative key
    patches = _apply_patches(_patch_llm(result=llm_resp))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["narrative"] == ""
    finally:
        _stop_patches(patches)


def test_comparison_passed_through_null():
    patches = _apply_patches(_patch_llm(result={**LLM_RESPONSE, "comparison": None}))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["comparison"] is None
    finally:
        _stop_patches(patches)


def test_comparison_passed_through_string():
    patches = _apply_patches(_patch_llm(result={**LLM_RESPONSE, "comparison": "Up 10%"}))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["comparison"] == "Up 10%"
    finally:
        _stop_patches(patches)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd query-forge-api && python -m pytest tests/services/test_query_studio_summary_service.py -v 2>&1 | head -40
```
Expected: ImportError — `query_studio_summary_service` does not exist yet.

- [ ] **Step 3: Implement the service**

Create `app/services/query_studio_summary_service.py`:

```python
"""
app/services/query_studio_summary_service.py

Stateless AI summary generation for Query Studio run previews.
Calls the shared analysis_utils LLM pipeline with row-capping.
No caching, no email, no digest snapshots — stateless per request.
"""
from __future__ import annotations

import os
import logging

from app.exceptions.forge_error import ForgeError
from app.exceptions.llm_unavailable_error import LLMUnavailableError
from app.skills.analysis_utils import (
    build_analysis_system_prompt,
    build_analysis_user_prompt,
    call_analysis_llm,
)

logger = logging.getLogger(__name__)


def generate_preview_summary(
    workspace_id: str,
    query_name: str,
    column_names: list[str],
    rows: list[dict],
    prompt_hint: str = "",
) -> dict:
    """
    Generate an AI summary of query preview results.

    Caps rows to QUERY_STUDIO_SUMMARY_MAX_ROWS before calling the LLM.
    Always passes the original (uncapped) row count to the user prompt.

    Returns:
        {narrative: str, highlights: list[str], comparison: any, capped: bool}

    Raises:
        LLMUnavailableError: when workspace has no LLM configured (ForgeError status 404)
        Any other exception from call_analysis_llm propagates unchanged.
    """
    max_rows = int(os.getenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", 100))
    original_row_count = len(rows)
    capped = original_row_count > max_rows
    capped_rows = rows[:max_rows]

    effective_hint = prompt_hint or ""
    if capped:
        effective_hint = (
            effective_hint
            + f" Note: this summary is based on the first {max_rows} rows of {original_row_count} total."
        ).lstrip()

    system_prompt = build_analysis_system_prompt(
        hint=effective_hint,
        include_comparison=False,
    )
    user_prompt = build_analysis_user_prompt(
        query_name=query_name,
        column_names=column_names,
        row_count=original_row_count,
        rows=capped_rows,
        previous_highlights=None,
        previous_run_date=None,
    )

    try:
        result = call_analysis_llm(
            workspace_id,
            system_prompt,
            user_prompt,
            max_tokens=600,
        )
    except ForgeError as exc:
        # ForgeError with status 404 = "No LLM configuration found for role"
        # ForgeError with status 400 = misconfigured LLM (missing model, endpoint, api_key)
        # Both represent "workspace LLM not available" from the caller's perspective.
        if exc.status_code in (400, 404):
            raise LLMUnavailableError(str(exc)) from exc
        raise

    return {
        "narrative": str(result.get("narrative") or ""),
        "highlights": list(result.get("highlights") or []),
        "comparison": result.get("comparison") or None,
        "capped": capped,
    }
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd query-forge-api && python -m pytest tests/services/test_query_studio_summary_service.py -v
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add query-forge-api/app/services/query_studio_summary_service.py \
        query-forge-api/tests/services/test_query_studio_summary_service.py
git commit -m "feat: add query studio summary service with row-capping and LLM call"
```

---

## Task 3: Backend — Summary route

**Files:**
- Create: `query-forge-api/app/routes/query_studio_summary_routes.py`

- [ ] **Step 1: Write the failing route tests**

Create `tests/routes/test_query_studio_summary_routes.py`:

```python
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import app.decorators.security as security
import app.routes.request_helpers as _route_utils
import app.routes.query_studio_summary_routes as summary_routes
from app.exceptions.llm_unavailable_error import LLMUnavailableError


def _headers(monkeypatch) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


VALID_BODY = {
    "workspace_id": "ws-1",
    "query_name": "Sales Report",
    "column_names": ["region", "revenue"],
    "rows": [{"region": "EMEA", "revenue": 100}],
}

GOOD_RESULT = {
    "narrative": "Strong EMEA performance.",
    "highlights": ["EMEA leads"],
    "comparison": None,
    "capped": False,
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_200_with_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    monkeypatch.setattr(summary_routes, "generate_preview_summary", lambda **kw: GOOD_RESULT)
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 200
    assert resp.json["capped"] is False
    assert resp.json["narrative"] == "Strong EMEA performance."


def test_200_with_empty_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    result_empty = {**GOOD_RESULT, "capped": False}
    monkeypatch.setattr(summary_routes, "generate_preview_summary", lambda **kw: result_empty)
    body = {**VALID_BODY, "rows": []}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation — 422
# ---------------------------------------------------------------------------

def test_422_missing_workspace_id(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "workspace_id"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_missing_query_name(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "query_name"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_missing_column_names(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "column_names"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_missing_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "rows"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_non_string_workspace_id(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {**VALID_BODY, "workspace_id": 123}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_non_array_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {**VALID_BODY, "rows": "not-an-array"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


# ---------------------------------------------------------------------------
# prompt_hint optional
# ---------------------------------------------------------------------------

def test_absent_prompt_hint_passed_as_empty_string(client, monkeypatch):
    headers = _headers(monkeypatch)
    captured = {}

    def _svc(**kw):
        captured.update(kw)
        return GOOD_RESULT

    monkeypatch.setattr(summary_routes, "generate_preview_summary", _svc)
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 200
    assert captured["prompt_hint"] == ""


def test_null_prompt_hint_passed_as_empty_string(client, monkeypatch):
    headers = _headers(monkeypatch)
    captured = {}

    def _svc(**kw):
        captured.update(kw)
        return GOOD_RESULT

    monkeypatch.setattr(summary_routes, "generate_preview_summary", _svc)
    body = {**VALID_BODY, "prompt_hint": None}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 200
    assert captured["prompt_hint"] == ""


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

def test_503_on_llm_unavailable(client, monkeypatch):
    headers = _headers(monkeypatch)
    monkeypatch.setattr(
        summary_routes,
        "generate_preview_summary",
        lambda **kw: (_ for _ in ()).throw(LLMUnavailableError("no llm")),
    )
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 503
    assert resp.json["code"] == "llm_unavailable"


def test_500_on_unhandled_llm_failure(client, monkeypatch):
    headers = _headers(monkeypatch)
    monkeypatch.setattr(
        summary_routes,
        "generate_preview_summary",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 500
    assert resp.json["code"] == "summary_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd query-forge-api && python -m pytest tests/routes/test_query_studio_summary_routes.py -v 2>&1 | head -20
```
Expected: ImportError — route module doesn't exist.

- [ ] **Step 3: Implement the route**

Create `app/routes/query_studio_summary_routes.py`:

```python
"""
app/routes/query_studio_summary_routes.py

POST /api/v1/query-studio/summarize
Generates an AI summary of a Run Preview result set.
"""
from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.exceptions.llm_unavailable_error import LLMUnavailableError
from app.services.query_studio_summary_service import generate_preview_summary

logger = logging.getLogger(__name__)

query_studio_summary_ns = Namespace(
    "query_studio_summary",
    description="Query Studio AI Result Summary",
)

_summarize_request = query_studio_summary_ns.model("SummarizeRequest", {
    "workspace_id": fields.String(required=True),
    "query_name": fields.String(required=True),
    "column_names": fields.List(fields.String(), required=True),
    "rows": fields.List(fields.Raw(), required=True),
    "prompt_hint": fields.String(required=False),
})

_summarize_response = query_studio_summary_ns.model("SummarizeResponse", {
    "narrative": fields.String(),
    "highlights": fields.List(fields.String()),
    "comparison": fields.String(allow_null=True),
    "capped": fields.Boolean(),
})


@query_studio_summary_ns.route("/summarize")
class QueryStudioSummarize(Resource):

    @token_required
    @query_studio_summary_ns.expect(_summarize_request)
    def post(self):
        body = request.get_json(silent=True) or {}

        # --- Validation ---
        workspace_id = body.get("workspace_id")
        query_name = body.get("query_name")
        column_names = body.get("column_names")
        rows = body.get("rows")
        prompt_hint = body.get("prompt_hint")

        if not isinstance(workspace_id, str) or not workspace_id.strip():
            return {"error": "workspace_id is required", "code": "validation_error"}, 422
        if not isinstance(query_name, str) or not query_name.strip():
            return {"error": "query_name is required", "code": "validation_error"}, 422
        if column_names is None or not isinstance(column_names, list):
            return {"error": "column_names is required and must be an array", "code": "validation_error"}, 422
        if rows is None or not isinstance(rows, list):
            return {"error": "rows is required and must be an array", "code": "validation_error"}, 422

        effective_hint = ""
        if isinstance(prompt_hint, str):
            effective_hint = prompt_hint

        # --- Dispatch ---
        try:
            result = generate_preview_summary(
                workspace_id=workspace_id,
                query_name=query_name,
                column_names=column_names,
                rows=rows,
                prompt_hint=effective_hint,
            )
        except LLMUnavailableError:
            return {"error": "LLM not configured for this workspace", "code": "llm_unavailable"}, 503
        except Exception:
            logger.exception("Summary generation failed")
            return {"error": "Summary generation failed", "code": "summary_failed"}, 500

        return result, 200
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd query-forge-api && python -m pytest tests/routes/test_query_studio_summary_routes.py -v
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add query-forge-api/app/routes/query_studio_summary_routes.py \
        query-forge-api/tests/routes/test_query_studio_summary_routes.py
git commit -m "feat: add query studio summary route POST /query-studio/summarize"
```

---

## Task 4: Backend — Feature registration

**Files:**
- Create: `query-forge-api/app/features/query_studio/__init__.py`
- Modify: `query-forge-api/app/features/__init__.py`

- [ ] **Step 1: Create the feature registrar**

Create `app/features/query_studio/__init__.py`:

```python
from app.routes.query_studio_summary_routes import query_studio_summary_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(query_studio_summary_ns, path=build_url("/", NAME, VERSION, "query-studio"))
```

- [ ] **Step 2: Register the feature in `app/features/__init__.py`**

Add to `app/features/__init__.py`:

```python
from .query_studio import register as register_query_studio
```

Add `register_query_studio` to the `FEATURE_REGISTRARS` list.

- [ ] **Step 3: Verify the app starts and the route is registered**

```bash
cd query-forge-api && python -c "
from app.factory import create_app
app = create_app()
with app.app_context():
    rules = [str(r) for r in app.url_map.iter_rules() if 'query-studio' in str(r)]
    print(rules)
"
```
Expected output includes `/api/v1/query-studio/summarize`.

- [ ] **Step 4: Run both new test files to confirm nothing regressed**

```bash
cd query-forge-api && python -m pytest tests/routes/test_query_studio_summary_routes.py tests/services/test_query_studio_summary_service.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add query-forge-api/app/features/query_studio/ \
        query-forge-api/app/features/__init__.py
git commit -m "feat: register query_studio feature with summarize namespace"
```

---

## Task 5: Backend — Bump version

**Files:**
- Modify: `query-forge-api/version.json`

- [ ] **Step 1: Bump backend version**

Edit `version.json`:
```json
{
  "version": "0.3.0"
}
```

- [ ] **Step 2: Commit**

```bash
git add query-forge-api/version.json
git commit -m "chore: bump backend version to 0.3.0 for query studio AI summary"
```

---

## Task 6: Frontend — API function

**Files:**
- Modify: `query-forge-ui/src/shared/services/api.ts`
- Modify: `query-forge-ui/src/shared/services/queryStudioAdminApi.ts`

- [ ] **Step 1: Add `/query-studio` to workspace-scoped prefixes**

In `src/shared/services/api.ts`, find `WORKSPACE_SCOPED_PREFIXES` and add `"/query-studio"` to the array.

- [ ] **Step 2: Add type and API function in `queryStudioAdminApi.ts`**

After the dictionary section (or wherever appropriate in the file), add:

```typescript
// ---------------------------------------------------------------------------
// QUERY STUDIO — AI Summary
// ---------------------------------------------------------------------------

export interface PreviewSummaryRequest {
  workspace_id: string;
  query_name: string;
  column_names: string[];
  rows: Record<string, unknown>[];
  prompt_hint?: string;
}

export interface PreviewSummaryResponse {
  narrative: string;
  highlights: string[];
  comparison: string | null;
  capped: boolean;
}

export async function summarizePreview(
  request: PreviewSummaryRequest,
): Promise<PreviewSummaryResponse> {
  const res = await api.post<PreviewSummaryResponse>(
    "/query-studio/summarize",
    request,
  );
  return res.data;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd query-forge-ui && npx tsc --noEmit 2>&1 | grep -v "node_modules" | head -20
```
Expected: no new errors introduced.

- [ ] **Step 4: Commit**

```bash
git add query-forge-ui/src/shared/services/api.ts \
        query-forge-ui/src/shared/services/queryStudioAdminApi.ts
git commit -m "feat: add summarizePreview API function for query studio AI summary"
```

---

## Task 7: Frontend — `useResultSummary` hook

**Files:**
- Create: `query-forge-ui/src/features/query-forge/ui/hooks/useResultSummary.ts`
- Create: `query-forge-ui/src/features/query-forge/ui/hooks/useResultSummary.test.ts`

- [ ] **Step 1: Write the failing hook tests**

Create `src/features/query-forge/ui/hooks/useResultSummary.test.ts`:

```typescript
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import * as api from "@/shared/services/queryStudioAdminApi";
import { useResultSummary } from "./useResultSummary";

const MOCK_SUMMARY = {
  narrative: "Test narrative",
  highlights: ["h1", "h2"],
  comparison: null,
  capped: false,
};

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

const BASE_OPTS = {
  workspaceId: "ws-1",
  queryName: "My Query",
  columnNames: ["col1"],
  rows: [{ col1: "a" }],
  enabled: true,
};

describe("useResultSummary", () => {
  let summarizeSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    summarizeSpy = vi.spyOn(api, "summarizePreview").mockResolvedValue({
      ...MOCK_SUMMARY,
      capped: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when enabled=false", async () => {
    const { result } = renderHook(
      () => useResultSummary({ ...BASE_OPTS, enabled: false }),
      { wrapper: makeWrapper() },
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(summarizeSpy).not.toHaveBeenCalled();
    expect(result.current.summary).toBeNull();
  });

  it("does not fetch when rows.length === 0 (caller passes enabled=false)", async () => {
    // Caller convention: enabled must be false when rows is empty
    const { result } = renderHook(
      () => useResultSummary({ ...BASE_OPTS, rows: [], enabled: false }),
      { wrapper: makeWrapper() },
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(summarizeSpy).not.toHaveBeenCalled();
    expect(result.current.summary).toBeNull();
  });

  it("fetches when enabled=true and rows present", async () => {
    const { result } = renderHook(
      () => useResultSummary(BASE_OPTS),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(summarizeSpy).toHaveBeenCalledOnce();
    expect(result.current.summary).not.toBeNull();
  });

  it("returns isLoading=true during fetch", () => {
    // Never resolves synchronously
    summarizeSpy.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(
      () => useResultSummary(BASE_OPTS),
      { wrapper: makeWrapper() },
    );
    expect(result.current.isLoading).toBe(true);
  });

  it("returns summary with all fields on success", async () => {
    summarizeSpy.mockResolvedValue({ ...MOCK_SUMMARY, capped: true });
    const { result } = renderHook(
      () => useResultSummary(BASE_OPTS),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.summary?.narrative).toBe("Test narrative");
    expect(result.current.summary?.highlights).toEqual(["h1", "h2"]);
    expect(result.current.summary?.capped).toBe(true);
    expect(result.current.summary?.totalRows).toBe(1);
  });

  it("returns isError=true on failure", async () => {
    summarizeSpy.mockRejectedValue(new Error("network error"));
    const { result } = renderHook(
      () => useResultSummary(BASE_OPTS),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("retry() triggers refetch", async () => {
    summarizeSpy.mockRejectedValueOnce(new Error("first fail")).mockResolvedValueOnce(MOCK_SUMMARY);
    const { result } = renderHook(
      () => useResultSummary(BASE_OPTS),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
    result.current.retry();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(summarizeSpy).toHaveBeenCalledTimes(2);
  });

  it("retry() is no-op when enabled=false", async () => {
    const { result } = renderHook(
      () => useResultSummary({ ...BASE_OPTS, enabled: false }),
      { wrapper: makeWrapper() },
    );
    result.current.retry();
    await new Promise((r) => setTimeout(r, 50));
    expect(summarizeSpy).not.toHaveBeenCalled();
  });

  it("query key change clears previous data and starts new fetch", async () => {
    const { result, rerender } = renderHook(
      (opts: typeof BASE_OPTS) => useResultSummary(opts),
      { wrapper: makeWrapper(), initialProps: BASE_OPTS },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.summary).not.toBeNull();

    // Change rows to trigger new query key
    rerender({ ...BASE_OPTS, rows: [{ col1: "CHANGED" }] });
    // Immediately after key change, should be loading with null summary
    expect(result.current.summary).toBeNull();
  });

  it("toggle off → on: if cached data exists, returns immediately without new fetch", async () => {
    // First render with enabled=true to populate cache
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client: queryClient }, children);

    const { result, rerender } = renderHook(
      (opts: { enabled: boolean }) => useResultSummary({ ...BASE_OPTS, enabled: opts.enabled }),
      { wrapper, initialProps: { enabled: true } },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(summarizeSpy).toHaveBeenCalledOnce();

    // Turn off
    rerender({ enabled: false });
    // Turn back on — data is cached, no new fetch
    rerender({ enabled: true });
    await new Promise((r) => setTimeout(r, 50));
    expect(summarizeSpy).toHaveBeenCalledOnce(); // still only one call
    expect(result.current.summary).not.toBeNull();
  });

  it("toggle off → on: if no cached data, triggers fetch", async () => {
    const { result, rerender } = renderHook(
      (opts: { enabled: boolean }) => useResultSummary({ ...BASE_OPTS, enabled: opts.enabled }),
      { wrapper: makeWrapper(), initialProps: { enabled: false } },
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(summarizeSpy).not.toHaveBeenCalled();

    // Enable — no cache exists → should fetch now
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(summarizeSpy).toHaveBeenCalledOnce();
    expect(result.current.summary).not.toBeNull();
  });

  it("query key is stable when column order changes but data is the same", () => {
    const rows = [{ b: 1, a: 2 }];
    const key1 = _computeKey("ws-1", "Q", ["a", "b"], rows);
    const key2 = _computeKey("ws-1", "Q", ["b", "a"], rows);
    expect(key1).toEqual(key2);
  });
});

// Helper to compute the fingerprint key the same way the hook does
function _computeKey(
  workspaceId: string,
  queryName: string,
  columnNames: string[],
  rows: Record<string, unknown>[],
) {
  const fingerprint = rows.slice(0, 5).map((row) =>
    JSON.stringify(
      Object.fromEntries(
        Object.entries(row).sort(([a], [b]) => a.localeCompare(b))
      )
    )
  ).join("|");
  return JSON.stringify([
    "resultSummary",
    workspaceId,
    queryName,
    columnNames.slice().sort().join(","),
    rows.length,
    fingerprint,
  ]);
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd query-forge-ui && npx vitest run src/features/query-forge/ui/hooks/useResultSummary.test.ts 2>&1 | tail -20
```
Expected: Module not found error.

- [ ] **Step 3: Implement the hook**

Ensure directory exists: `src/features/query-forge/ui/hooks/`

Create `src/features/query-forge/ui/hooks/useResultSummary.ts`:

```typescript
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { summarizePreview } from "@/shared/services/queryStudioAdminApi";

export interface UseResultSummaryOptions {
  workspaceId: string;
  queryName: string;
  columnNames: string[];
  rows: Record<string, unknown>[];
  enabled: boolean;
}

export interface SummaryResult {
  narrative: string | null;
  highlights: string[];
  comparison: string | null;
  capped: boolean;
  totalRows: number;
}

export interface UseResultSummaryResult {
  summary: SummaryResult | null;
  isLoading: boolean;
  isError: boolean;
  retry: () => void;
}

function buildQueryKey(
  workspaceId: string,
  queryName: string,
  columnNames: string[],
  rows: Record<string, unknown>[],
) {
  const fingerprint = rows.slice(0, 5).map((row) =>
    JSON.stringify(
      Object.fromEntries(
        Object.entries(row).sort(([a], [b]) => a.localeCompare(b))
      )
    )
  ).join("|");
  return [
    "resultSummary",
    workspaceId,
    queryName,
    columnNames.slice().sort().join(","),
    rows.length,
    fingerprint,
  ];
}

export function useResultSummary({
  workspaceId,
  queryName,
  columnNames,
  rows,
  enabled,
}: UseResultSummaryOptions): UseResultSummaryResult {
  const queryKey = buildQueryKey(workspaceId, queryName, columnNames, rows);
  const queryClient = useQueryClient();

  const { data, isFetching, isError, refetch } = useQuery<SummaryResult>({
    queryKey,
    queryFn: async () => {
      const res = await summarizePreview({
        workspace_id: workspaceId,
        query_name: queryName,
        column_names: columnNames,
        rows,
      });
      return {
        narrative: res.narrative || null,
        highlights: res.highlights ?? [],
        comparison: res.comparison ?? null,
        capped: res.capped,
        totalRows: rows.length,
      };
    },
    enabled,
    placeholderData: undefined, // never retain previous data for a new key
    staleTime: 0,
    gcTime: 5 * 60 * 1000,
    retry: false,
  });

  return {
    summary: data ?? null,
    isLoading: isFetching && !data,
    isError,
    retry: () => {
      if (!enabled) return;
      void refetch();
    },
  };
}
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd query-forge-ui && npx vitest run src/features/query-forge/ui/hooks/useResultSummary.test.ts
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add query-forge-ui/src/features/query-forge/ui/hooks/useResultSummary.ts \
        query-forge-ui/src/features/query-forge/ui/hooks/useResultSummary.test.ts
git commit -m "feat: add useResultSummary hook for query studio AI summary"
```

---

## Task 8: Frontend — `ResultSummary` component

**Files:**
- Create: `query-forge-ui/src/features/query-forge/ui/components/ResultSummary/ResultSummary.tsx`
- Create: `query-forge-ui/src/features/query-forge/ui/components/ResultSummary/ResultSummary.test.tsx`

- [ ] **Step 1: Write the failing component tests**

Create `src/features/query-forge/ui/components/ResultSummary/ResultSummary.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { ResultSummary } from "./ResultSummary";
import type { SummaryResult } from "../../hooks/useResultSummary";

const MOCK_SUMMARY: SummaryResult = {
  narrative: "Strong performance.",
  highlights: ["EMEA leads at 62%", "Revenue up 10%"],
  comparison: null,
  capped: false,
  totalRows: 50,
};

describe("ResultSummary", () => {
  // Loading
  it("renders loading skeleton while isLoading=true", () => {
    render(
      <ResultSummary
        summary={null}
        isLoading={true}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByTestId("result-summary-skeleton")).toBeInTheDocument();
  });

  // Highlights
  it("renders highlights as bullet list when present", () => {
    render(
      <ResultSummary
        summary={MOCK_SUMMARY}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("EMEA leads at 62%")).toBeInTheDocument();
    expect(screen.getByText("Revenue up 10%")).toBeInTheDocument();
  });

  it("does not render bullet list when highlights is empty", () => {
    render(
      <ResultSummary
        summary={{ ...MOCK_SUMMARY, highlights: [] }}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  // Narrative
  it("renders narrative as prose when present", () => {
    render(
      <ResultSummary
        summary={MOCK_SUMMARY}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("Strong performance.")).toBeInTheDocument();
  });

  it("does not render narrative block when null", () => {
    render(
      <ResultSummary
        summary={{ ...MOCK_SUMMARY, narrative: null }}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    // No empty <p>
    const paragraphs = document.querySelectorAll("p");
    paragraphs.forEach((p) => expect(p.textContent).not.toBe(""));
  });

  it("does not render narrative block when empty string", () => {
    render(
      <ResultSummary
        summary={{ ...MOCK_SUMMARY, narrative: "" }}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("result-summary-narrative")).not.toBeInTheDocument();
  });

  // Capped
  it("renders capped disclaimer when capped=true", () => {
    render(
      <ResultSummary
        summary={{ ...MOCK_SUMMARY, capped: true, totalRows: 5000 }}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText(/Summary based on first/)).toBeInTheDocument();
    expect(screen.getByText(/5,000/)).toBeInTheDocument();
  });

  it("does not render capped disclaimer when capped=false", () => {
    render(
      <ResultSummary
        summary={{ ...MOCK_SUMMARY, capped: false }}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Summary based on first/)).not.toBeInTheDocument();
  });

  // Comparison
  it("renders comparison when non-null", () => {
    render(
      <ResultSummary
        summary={{ ...MOCK_SUMMARY, comparison: "Up 10% vs last week" }}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText(/Up 10% vs last week/)).toBeInTheDocument();
  });

  it("does not render comparison block when null", () => {
    render(
      <ResultSummary
        summary={{ ...MOCK_SUMMARY, comparison: null }}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("result-summary-comparison")).not.toBeInTheDocument();
  });

  // Error
  it("renders error message and Retry button on isError=true", () => {
    render(
      <ResultSummary
        summary={null}
        isLoading={false}
        isError={true}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText(/Summary unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("Retry button calls onRetry", () => {
    const onRetry = vi.fn();
    render(
      <ResultSummary
        summary={null}
        isLoading={false}
        isError={true}
        isVisible={true}
        onRetry={onRetry}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("Retry button not rendered when isVisible=false", () => {
    render(
      <ResultSummary
        summary={null}
        isLoading={false}
        isError={true}
        isVisible={false}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  // Collapse/expand
  it("section is expanded by default", () => {
    render(
      <ResultSummary
        summary={MOCK_SUMMARY}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByTestId("result-summary-content")).toBeVisible();
  });

  it("chevron collapses/expands content on click", () => {
    render(
      <ResultSummary
        summary={MOCK_SUMMARY}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    const toggle = screen.getByTestId("result-summary-toggle");
    fireEvent.click(toggle);
    expect(screen.getByTestId("result-summary-content")).not.toBeVisible();
    fireEvent.click(toggle);
    expect(screen.getByTestId("result-summary-content")).toBeVisible();
  });

  // Visibility
  it("isVisible=false applies display:none to container, component remains mounted", () => {
    render(
      <ResultSummary
        summary={MOCK_SUMMARY}
        isLoading={false}
        isError={false}
        isVisible={false}
        onRetry={vi.fn()}
      />,
    );
    const container = screen.getByTestId("result-summary-container");
    expect(container).toHaveStyle({ display: "none" });
    // Component is mounted — narrative text is in the DOM
    expect(screen.getByText("Strong performance.")).toBeInTheDocument();
  });

  it("isVisible=true — container is visible", () => {
    render(
      <ResultSummary
        summary={MOCK_SUMMARY}
        isLoading={false}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    const container = screen.getByTestId("result-summary-container");
    expect(container).not.toHaveStyle({ display: "none" });
  });

  it("does not auto-reopen on retry — section stays collapsed after user collapses and retries", () => {
    const { rerender } = render(
      <ResultSummary
        summary={null}
        isLoading={false}
        isError={true}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    // Collapse it
    const toggle = screen.getByTestId("result-summary-toggle");
    fireEvent.click(toggle);
    expect(screen.getByTestId("result-summary-content")).not.toBeVisible();

    // Retry (same key — no new preview, no key change)
    rerender(
      <ResultSummary
        summary={null}
        isLoading={true}
        isError={false}
        isVisible={true}
        onRetry={vi.fn()}
      />,
    );
    // Section should NOT reopen automatically
    expect(screen.getByTestId("result-summary-content")).not.toBeVisible();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd query-forge-ui && npx vitest run src/features/query-forge/ui/components/ResultSummary/ResultSummary.test.tsx 2>&1 | tail -10
```
Expected: Module not found.

- [ ] **Step 3: Implement the component**

Create `src/features/query-forge/ui/components/ResultSummary/ResultSummary.tsx`:

```tsx
import React, { useState } from "react";
import type { SummaryResult } from "../../hooks/useResultSummary";

const MAX_ROWS_DISPLAY = 100;

export interface ResultSummaryProps {
  summary: SummaryResult | null;
  isLoading: boolean;
  isError: boolean;
  isVisible: boolean;
  onRetry: () => void;
}

export const ResultSummary: React.FC<ResultSummaryProps> = ({
  summary,
  isLoading,
  isError,
  isVisible,
  onRetry,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div
      data-testid="result-summary-container"
      style={{
        display: isVisible ? undefined : "none",
        marginBottom: 12,
      }}
    >
      {/* Header */}
      <div
        data-testid="result-summary-toggle"
        className="d-flex align-items-center gap-2"
        style={{
          cursor: "pointer",
          userSelect: "none",
          padding: "6px 0",
          fontSize: 13,
          fontWeight: 600,
          color: "rgba(0,0,0,0.75)",
        }}
        onClick={() => setIsExpanded((v) => !v)}
        role="button"
        aria-expanded={isExpanded}
      >
        <i
          className={`fa fa-chevron-${isExpanded ? "down" : "right"}`}
          style={{ fontSize: 10, marginRight: 4 }}
        />
        <span style={{ filter: "hue-rotate(-30deg) saturate(2)" }}>✨</span>
        AI Summary
      </div>

      {/* Body */}
      <div
        data-testid="result-summary-content"
        style={{
          display: isExpanded ? undefined : "none",
          borderLeft: "3px solid #7c3aed",
          background: "rgba(124, 58, 237, 0.04)",
          borderRadius: "0 8px 8px 0",
          padding: "10px 14px",
          fontSize: 13,
        }}
      >
        {isLoading && (
          <div data-testid="result-summary-skeleton">
            <div className="placeholder-glow">
              <span className="placeholder col-7 mb-1 d-block" />
              <span className="placeholder col-5 mb-1 d-block" />
              <span className="placeholder col-9 mb-1 d-block" />
            </div>
          </div>
        )}

        {!isLoading && isError && (
          <div className="d-flex align-items-center gap-2 text-muted">
            <span>Summary unavailable</span>
            {isVisible && (
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={onRetry}
              >
                Retry
              </button>
            )}
          </div>
        )}

        {!isLoading && !isError && summary && (
          <>
            {summary.highlights.length > 0 && (
              <ul className="mb-2 ps-3" style={{ lineHeight: 1.6 }}>
                {summary.highlights.map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
            )}

            {summary.narrative && (
              <p
                data-testid="result-summary-narrative"
                className="mb-2"
                style={{ lineHeight: 1.6 }}
              >
                {summary.narrative}
              </p>
            )}

            {summary.capped && (
              <div
                className="text-muted"
                style={{ fontSize: 11, fontStyle: "italic" }}
              >
                Summary based on first {MAX_ROWS_DISPLAY.toLocaleString()} of{" "}
                {summary.totalRows.toLocaleString()} rows.
              </div>
            )}

            {summary.comparison && (
              <div
                data-testid="result-summary-comparison"
                className="mt-2 text-muted"
                style={{ fontSize: 12 }}
              >
                vs previous run: {summary.comparison}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd query-forge-ui && npx vitest run src/features/query-forge/ui/components/ResultSummary/ResultSummary.test.tsx
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add query-forge-ui/src/features/query-forge/ui/components/ResultSummary/ \
        query-forge-ui/src/features/query-forge/ui/hooks/
git commit -m "feat: add ResultSummary component for query studio AI summary panel"
```

---

## Task 9: Frontend — Wire up into PreviewSection

**Files:**
- Modify: `query-forge-ui/src/features/query-forge/ui/components/PreviewSection.tsx`

The existing file is `PreviewSection.tsx` (exports `PreviewCard`). The relevant sections are:
- `right` JSX (line ~487) — where Skills, Analyze, Export Excel, Cancel, and Run Preview buttons live
- `showAnalysis` + `QueryAnalysisPanel` block (line ~728) — just before the data table
- Props include: `workspaceId`, `exportBaseName`, `queryId`

- [ ] **Step 1: Add imports**

At the top of `PreviewSection.tsx`, after existing imports, add:

```tsx
import { useState as _useState } from "react";
import { ResultSummary } from "./ResultSummary/ResultSummary";
import { useResultSummary } from "../hooks/useResultSummary";
```

Note: `useState` is already imported — use the existing import. Just add `ResultSummary` and `useResultSummary`.

- [ ] **Step 2: Add `summaryEnabled` state**

Inside the `PreviewCard` component body, alongside the other `useState` calls (near line 128):

```tsx
const [summaryEnabled, setSummaryEnabled] = useState(true);
```

- [ ] **Step 3: Wire the hook**

After the `const rows = ...` line (near line 178), add:

```tsx
const {
  summary: resultSummary,
  isLoading: isSummaryLoading,
  isError: isSummaryError,
  retry: retrySummary,
} = useResultSummary({
  workspaceId: String(workspaceId ?? ""),
  queryName: exportBaseName ?? "Draft Query",
  columnNames: columns.map((c) => c.key),
  rows: rows as Record<string, unknown>[],
  enabled: rows.length > 0,
});
```

- [ ] **Step 4: Add AI Summary toggle to the `right` bar**

In the `right` JSX block, before the existing Analyze button:

```tsx
<div className="d-flex align-items-center gap-1">
  <label
    htmlFor="ai-summary-toggle"
    className="form-check-label small text-muted mb-0"
    style={{ cursor: "pointer" }}
  >
    AI Summary
  </label>
  <div className="form-check form-switch mb-0 ms-1">
    <input
      id="ai-summary-toggle"
      type="checkbox"
      className="form-check-input"
      checked={summaryEnabled}
      onChange={(e) => setSummaryEnabled(e.target.checked)}
      title={summaryEnabled ? "Disable AI Summary" : "Enable AI Summary"}
    />
  </div>
</div>
```

- [ ] **Step 5: Render `<ResultSummary>` between header bar and data table**

In the results view JSX (the `ncq-view` div), after the `ncq-toolbar` div and before the `{showAnalysis && ...}` block, add:

```tsx
<ResultSummary
  summary={resultSummary}
  isLoading={isSummaryLoading}
  isError={isSummaryError}
  isVisible={summaryEnabled && rows.length > 0}
  onRetry={retrySummary}
/>
```

- [ ] **Step 6: Verify TypeScript compiles without new errors**

```bash
cd query-forge-ui && npx tsc --noEmit 2>&1 | grep -v "node_modules" | head -30
```
Expected: no new errors introduced (pre-existing errors are allowed).

- [ ] **Step 7: Run all query-forge tests**

```bash
cd query-forge-ui && npx vitest run src/features/query-forge/ 2>&1 | tail -20
```
Expected: All new tests pass; no existing tests regressed.

- [ ] **Step 8: Commit**

```bash
git add query-forge-ui/src/features/query-forge/ui/components/PreviewSection.tsx
git commit -m "feat: wire ResultSummary and AI Summary toggle into PreviewSection"
```

---

## Task 10: Frontend — Bump version

**Files:**
- Modify: `query-forge-ui/package.json`

- [ ] **Step 1: Bump frontend version**

In `package.json`, change `"version": "0.2.0"` → `"version": "0.3.0"`.

- [ ] **Step 2: Commit**

```bash
git add query-forge-ui/package.json
git commit -m "chore: bump frontend version to 0.3.0 for query studio AI summary"
```

---

## Task 11: Update `query-forge-api/memory.md`

**Files:**
- Modify: `query-forge-api/memory.md`

- [ ] **Step 1: Append summary entry to memory.md**

Add a new section to `query-forge-api/memory.md` summarizing this feature.

- [ ] **Step 2: Commit**

```bash
git add query-forge-api/memory.md
git commit -m "docs: update memory.md with query studio AI summary feature"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] `cd query-forge-api && python -m pytest tests/services/test_query_studio_summary_service.py tests/routes/test_query_studio_summary_routes.py -v` — all pass
- [ ] `cd query-forge-api && ./scripts/lint.sh` — no new lint errors
- [ ] `cd query-forge-ui && npx vitest run src/features/query-forge/` — all pass
- [ ] `cd query-forge-ui && npx tsc --noEmit` — no new TypeScript errors
- [ ] Backend `version.json` is `0.3.0`
- [ ] Frontend `package.json` version is `0.3.0`
- [ ] `query-forge-api/memory.md` has been updated
