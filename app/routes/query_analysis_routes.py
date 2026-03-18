"""
app/routes/query_analysis_routes.py

Inline AI analysis endpoint for the Query Studio.

POST /api/v1/queries/<query_id>/analyze

Data source: the backend re-executes the saved query and analyzes those
results. Frontend table rows are never sent to the LLM. This ensures
analysis always reflects the full dataset, not a paginated UI slice.

Authorization: user must have access to the query via the existing
query execution path. Workspace header must match query ownership.
Unauthorized access returns 404 (same as query not found) to avoid
leaking query existence.

Caching: results cached in Valkey for 5 minutes. The server always
computes the canonical hash from its own execution results. The client
may send a result_hash as a hint to avoid re-execution, but the server
validates this against its own hash before returning cached data.

Observability: every request logs a structured analytics line including
cache_hit, llm_latency_ms, sampled_rows, and error_type.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from flask import g, request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.routes.request_helpers import extract_workspace_id
from app.skills.analysis_utils import (
    MAX_SAMPLE_ROWS,
    build_analysis_system_prompt,
    build_analysis_user_prompt,
    call_analysis_llm,
    result_hash,
)

logger = logging.getLogger(__name__)

query_analysis_ns = Namespace("query_analysis", description="Inline Query AI Analysis")

CACHE_TTL_SECONDS = 300
CACHE_KEY_PREFIX = "qf:analysis:"

# ---------------------------------------------------------------------------
# Swagger model
# ---------------------------------------------------------------------------

analyze_request_model = query_analysis_ns.model("AnalyzeRequest", {
    "prompt_hint": fields.String(
        description="Optional LLM guidance (e.g. 'Focus on revenue anomalies')",
        example="Focus on data quality issues",
    ),
    "result_hash": fields.String(
        description="Hash from a previous response. Used as cache hint only — server recomputes.",
        example="a3f9b12c45678901",
    ),
})


# ---------------------------------------------------------------------------
# POST /api/v1/queries/<query_id>/analyze
# ---------------------------------------------------------------------------


@query_analysis_ns.route("/<string:query_id>/analyze")
class QueryAnalyze(Resource):
    @token_required
    @query_analysis_ns.expect(analyze_request_model)
    def post(self, query_id: str):
        """
        Generate an AI analysis of a query's current results.

        Data source: backend re-executes the query. UI table rows
        are not used. Analysis always reflects the full dataset.

        Returns narrative + highlights + dataset profile metadata.
        Cached per result hash for 5 minutes.
        """
        workspace_id = extract_workspace_id()
        body = request.json or {}
        prompt_hint = body.get("prompt_hint", "").strip()
        client_hash = body.get("result_hash", "").strip()

        obs = _Observability(query_id=query_id, workspace_id=workspace_id)

        # 1. Check LLM availability before doing any work
        if not _check_llm_available(workspace_id):
            obs.log(error_type="no_llm")
            return {
                "error": "No LLM configured for this workspace.",
                "hint": "Configure a workspace LLM under Settings → LLM Configuration.",
            }, 503

        # 2. If client sent a hash, try cache hit before re-execution
        if client_hash:
            cached = _get_cache(workspace_id, query_id, client_hash)
            if cached:
                obs.log(cache_hit=True)
                return {**cached, "cached": True}, 200

        # 3. Execute query (authorisation is enforced here — 404 if no access)
        try:
            t0 = time.monotonic()
            query_results = _run_query(query_id, workspace_id)
            obs.query_ms = int((time.monotonic() - t0) * 1000)
            obs.sampled_rows = min(len(query_results["rows"]), MAX_SAMPLE_ROWS)
        except ValueError as exc:
            obs.log(error_type="not_found")
            return {"error": str(exc)}, 404
        except Exception as exc:
            logger.exception("Query execution failed for analysis query_id=%s", query_id)
            obs.log(error_type="query_error")
            return {"error": f"Query execution failed: {exc}"}, 500

        # 4. Compute server-side canonical hash
        # Client hash is a hint only — server ALWAYS recomputes from its results
        canonical_hash = result_hash(query_results["rows"], query_results["row_count"])

        # 5. Check cache again with canonical hash
        cached = _get_cache(workspace_id, query_id, canonical_hash)
        if cached:
            obs.log(cache_hit=True)
            return {**cached, "cached": True, "result_hash": canonical_hash}, 200

        # 6. Build prompts
        # Note: inline analysis never uses comparison — no saved state exists here
        system_prompt = build_analysis_system_prompt(
            hint=prompt_hint,
            include_comparison=False,  # always False for inline analysis
        )
        user_prompt = build_analysis_user_prompt(
            query_name=query_results["query_name"],
            column_names=query_results["column_names"],
            row_count=query_results["row_count"],
            rows=query_results["rows"],
            previous_highlights=None,   # not available in inline analysis
            previous_run_date=None,     # not available in inline analysis
        )

        # 7. Call LLM
        try:
            t0 = time.monotonic()
            analysis = call_analysis_llm(
                workspace_id=workspace_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=600,
            )
            obs.llm_ms = int((time.monotonic() - t0) * 1000)
        except Exception as exc:
            logger.warning("LLM analysis failed for query_id=%s: %s", query_id, exc)
            obs.log(error_type="llm_error")
            return {"error": f"AI analysis unavailable: {exc}"}, 502

        # 8. Build response, cache, return
        response = {
            "narrative": analysis["narrative"],
            "highlights": analysis["highlights"],
            "query_name": query_results["query_name"],
            "row_count": query_results["row_count"],
            "sampled_rows": obs.sampled_rows,
            "result_hash": canonical_hash,
            "cached": False,
        }
        _set_cache(workspace_id, query_id, canonical_hash, response)
        obs.log(cache_hit=False)
        return response, 200


# ---------------------------------------------------------------------------
# POST /api/v1/queries/analyze  (inline — unsaved queries)
# ---------------------------------------------------------------------------


analyze_inline_request_model = query_analysis_ns.model("AnalyzeInlineRequest", {
    "rows": fields.List(fields.Raw(), description="Result rows as objects"),
    "column_names": fields.List(fields.String(), description="Column names in order"),
    "row_count": fields.Integer(description="Total row count"),
    "query_name": fields.String(description="Display name for the query"),
    "prompt_hint": fields.String(description="Optional LLM guidance"),
    "result_hash": fields.String(description="Cache hint from previous response"),
})


@query_analysis_ns.route("/analyze")
class QueryAnalyzeInline(Resource):
    @token_required
    @query_analysis_ns.expect(analyze_inline_request_model)
    def post(self):
        """
        Analyze inline rows for an unsaved/draft query.
        Rows are provided in the request body — no DB lookup or re-execution.
        """
        workspace_id = extract_workspace_id()
        body = request.json or {}
        prompt_hint = body.get("prompt_hint", "").strip()
        client_hash = body.get("result_hash", "").strip()
        rows = body.get("rows") or []
        column_names = body.get("column_names") or []
        row_count = int(body.get("row_count") or len(rows))
        query_name = (body.get("query_name") or "Draft Query").strip()

        obs = _Observability(query_id="inline", workspace_id=workspace_id)

        if not _check_llm_available(workspace_id):
            obs.log(error_type="no_llm")
            return {
                "error": "No LLM configured for this workspace.",
                "hint": "Configure a workspace LLM under Settings → LLM Configuration.",
            }, 503

        if client_hash:
            cached = _get_cache(workspace_id, "inline", client_hash)
            if cached:
                obs.log(cache_hit=True)
                return {**cached, "cached": True}, 200

        canonical_hash = result_hash(rows, row_count)
        cached = _get_cache(workspace_id, "inline", canonical_hash)
        if cached:
            obs.log(cache_hit=True)
            return {**cached, "cached": True, "result_hash": canonical_hash}, 200

        obs.sampled_rows = min(len(rows), MAX_SAMPLE_ROWS)

        system_prompt = build_analysis_system_prompt(
            hint=prompt_hint,
            include_comparison=False,
        )
        user_prompt = build_analysis_user_prompt(
            query_name=query_name,
            column_names=column_names,
            row_count=row_count,
            rows=rows,
        )

        try:
            t0 = time.monotonic()
            analysis = call_analysis_llm(
                workspace_id=workspace_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=600,
            )
            obs.llm_ms = int((time.monotonic() - t0) * 1000)
        except Exception as exc:
            logger.warning("LLM inline analysis failed: %s", exc)
            obs.log(error_type="llm_error")
            return {"error": f"AI analysis unavailable: {exc}"}, 502

        response = {
            "narrative": analysis["narrative"],
            "highlights": analysis["highlights"],
            "query_name": query_name,
            "row_count": row_count,
            "sampled_rows": obs.sampled_rows,
            "result_hash": canonical_hash,
            "cached": False,
        }
        _set_cache(workspace_id, "inline", canonical_hash, response)
        obs.log(cache_hit=False)
        return response, 200


# ---------------------------------------------------------------------------
# Observability helper
# ---------------------------------------------------------------------------


class _Observability:
    """Collects metrics for a single analysis request and logs them."""

    def __init__(self, query_id: str, workspace_id: str):
        self.query_id = query_id
        self.workspace_id = workspace_id
        self.llm_ms: int | None = None
        self.query_ms: int | None = None
        self.sampled_rows: int | None = None

    def log(self, cache_hit: bool = False, error_type: str | None = None) -> None:
        logger.info(
            "analysis_request",
            extra={
                "event": "analysis_request",
                "query_id": self.query_id,
                "workspace_id": self.workspace_id,
                "cache_hit": cache_hit,
                "llm_latency_ms": self.llm_ms,
                "query_latency_ms": self.query_ms,
                "sampled_rows": self.sampled_rows,
                "error_type": error_type,
            },
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _check_llm_available(workspace_id: str) -> bool:
    try:
        from app.services.tenancy.workspace_llm_service import WorkspaceLLMService
        return WorkspaceLLMService().get_llm_for_role(workspace_id, "default") is not None
    except Exception:
        return False


def _run_query(query_id: str, workspace_id: str) -> dict:
    """
    Execute the query and return normalised results.

    Authorization: this function uses the existing query execution path
    which enforces workspace ownership. If the query does not belong to
    the workspace, it raises ValueError (same as not found). This means
    unauthorized access returns 404, not 403, to avoid leaking existence.

    SEAM: same implementation as skill_runner._run_query() — keep in sync.
    """
    import json as _json
    from app.adapters.mysql_sql_executor import ForgeMetaSQL
    from app.services.domain_resolver import DomainResolver
    from app.services.query_forge_service import QueryForgeService
    from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

    rows_q = ForgeMetaSQL().execute_query_mappings(
        "SELECT sql_json, name FROM saved_query "
        "WHERE id = :id AND workspace_id = :ws AND is_deleted = 0 LIMIT 1",
        {"id": query_id, "ws": workspace_id},
    )
    if not rows_q:
        raise ValueError(f"Query {query_id} not found in workspace {workspace_id}.")

    sql_json = rows_q[0]["sql_json"]
    if isinstance(sql_json, str):
        sql_json = _json.loads(sql_json)
    sql_json = sql_json or {}
    query_name = rows_q[0].get("name", f"Query {query_id}")

    ctx = WorkspaceSqlContextBuilder().build(workspace_id)
    svc = QueryForgeService(
        executor=ctx.sql_exec,
        domain_resolver=DomainResolver(workspace_id=workspace_id),
    )
    result = svc.run(raw_query=sql_json, mode="export", limit=500, offset=0)

    columns = result.columns or []
    rows = result.rows or []

    return {
        "rows": rows,
        "query_name": query_name,
        "column_names": columns,
        "row_count": result.total if result.total is not None else len(rows),
    }


def _cache_key(workspace_id: str, query_id: str, hash_val: str) -> str:
    return f"{CACHE_KEY_PREFIX}{workspace_id}:{query_id}:{hash_val}"


def _get_cache(workspace_id: str, query_id: str, hash_val: str) -> dict | None:
    if not hash_val:
        return None
    try:
        import valkey
        from app.config import VALKEY_ADDRESS, VALKEY_PORT
        client = valkey.Valkey(
            host=str(VALKEY_ADDRESS or "localhost"),
            port=int(VALKEY_PORT or 6379),
            db=0, decode_responses=True, socket_timeout=1.0,
        )
        raw = client.get(_cache_key(workspace_id, query_id, hash_val))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("Cache read failed (non-fatal): %s", exc)
        return None


def _set_cache(workspace_id: str, query_id: str, hash_val: str, data: dict) -> None:
    try:
        import valkey
        from app.config import VALKEY_ADDRESS, VALKEY_PORT
        client = valkey.Valkey(
            host=str(VALKEY_ADDRESS or "localhost"),
            port=int(VALKEY_PORT or 6379),
            db=0, decode_responses=True, socket_timeout=1.0,
        )
        client.setex(
            _cache_key(workspace_id, query_id, hash_val),
            CACHE_TTL_SECONDS,
            json.dumps(data),
        )
    except Exception as exc:
        logger.debug("Cache write failed (non-fatal): %s", exc)
