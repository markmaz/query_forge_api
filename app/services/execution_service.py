from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any, Dict, Optional

import valkey

from app.config import VALKEY_ADDRESS, VALKEY_PORT
from app.exceptions.service_error import ServiceError
from app.services.domain_resolver import DomainResolver
from app.services.no_code_query_service import NoCodeQueryService
from app.services.sql_guard_service import assert_no_disallowed_client_sql_fields, assert_read_only_sql_statement
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder

logger = logging.getLogger(__name__)

_JOB_TTL_S = 30 * 60
_valkey_client: Optional[valkey.StrictValkey] = None


def _utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _get_valkey_client() -> valkey.StrictValkey:
    global _valkey_client
    if _valkey_client is None:
        _valkey_client = valkey.StrictValkey(
            host=VALKEY_ADDRESS,
            port=VALKEY_PORT,
            decode_responses=True,
        )
    return _valkey_client


def _job_key(job_id: str) -> str:
    return f"exec:job:{job_id}"


def _put_job(job_id: str, payload: Dict[str, Any]) -> None:
    payload = dict(payload)
    payload.setdefault("created_at", _utc_now_iso())
    data = json.dumps(payload, default=str)
    _get_valkey_client().setex(_job_key(job_id), _JOB_TTL_S, data)


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    data = _get_valkey_client().get(_job_key(job_id))
    if not data:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def _columns_from_manifest(manifest: Optional[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not isinstance(manifest, dict):
        return []
    schema = manifest.get("schema") or {}
    columns = schema.get("columns") or []
    if not isinstance(columns, list):
        return []
    out: list[Dict[str, Any]] = []
    for col in columns:
        if not isinstance(col, dict):
            continue
        name = col.get("name")
        if not name:
            continue
        item = {"key": name, "label": name}
        if "type" in col:
            item["dataType"] = col.get("type")
        if "nullable" in col:
            item["nullable"] = col.get("nullable")
        out.append(item)
    return out


def _columns_from_rows(rows: list[Any]) -> list[Dict[str, Any]]:
    if not rows:
        return []
    first = rows[0]
    if isinstance(first, dict):
        return [{"key": k, "label": k} for k in first.keys()]
    return []


def _rows_to_dicts(rows_any: list[Any], columns: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not rows_any:
        return []
    if rows_any and isinstance(rows_any[0], dict):
        return rows_any
    if not columns:
        return []
    keys = [c.get("key") for c in columns]
    out: list[Dict[str, Any]] = []
    for row in rows_any:
        if not isinstance(row, (list, tuple)):
            continue
        out.append({keys[i]: (row[i] if i < len(row) else None) for i in range(len(keys))})
    return out


def _int_from_payload(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ServiceError(f"Invalid integer for '{name}'", status_code=400)


def _int_from_args(args: Dict[str, Any], name: str, default: int) -> int:
    raw = (args.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ServiceError(f"Invalid integer for '{name}'", status_code=400)


def _extract_total(count_rows: list[Any]) -> int:
    if not count_rows:
        return 0
    first = count_rows[0]
    if isinstance(first, dict):
        return int(first.get("total") or 0)
    if isinstance(first, (list, tuple)) and len(first) >= 1:
        return int(first[0] or 0)
    return 0


class ExecutionService:
    def __init__(self, context_builder: Optional[WorkspaceContextBuilder] = None):
        self._builder = context_builder or WorkspaceContextBuilder()

    def start(self, workspace_id: str, payload: Dict[str, Any], query_args: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
        assert_no_disallowed_client_sql_fields(payload)

        sql_json = payload.get("sqlJson") or payload.get("sql_json")
        if sql_json is None:
            raise ServiceError("sqlJson is required", status_code=400)
        if sql_json is not None and not isinstance(sql_json, dict):
            raise ServiceError("sqlJson must be an object", status_code=400)

        sql = ""
        params: Dict[str, Any] = {}

        kind = (payload.get("kind") or "").strip()
        if not kind and isinstance(sql_json, dict):
            meta = sql_json.get("meta") if isinstance(sql_json.get("meta"), dict) else {}
            tool = (meta.get("tool") or "").strip().lower()
            if tool == "cohort_builder":
                kind = "cohort_builder"
            else:
                kind = "query_builder"
        if kind not in ("query_builder", "cohort_builder"):
            raise ServiceError("kind must be query_builder or cohort_builder", status_code=400)

        ctx = self._builder.build(workspace_id)
        limit_raw = _int_from_payload(payload.get("limit"), "limit")
        offset_raw = _int_from_payload(payload.get("offset"), "offset")
        limit = limit_raw if limit_raw is not None else _int_from_args(query_args, "limit", 200)
        offset = offset_raw if offset_raw is not None else _int_from_args(query_args, "offset", 0)

        sql_rendered = None
        count_sql = None
        domain_resolver = DomainResolver(workspace_id=workspace_id)
        svc = NoCodeQueryService(executor=ctx.sql_exec, domain_resolver=domain_resolver)
        mode = (query_args.get("mode") or "preview").strip().lower()
        prepared = svc.prepare(raw_query=sql_json, mode=mode, limit=limit, offset=offset)
        sql = prepared.sql
        params = prepared.params
        sql_rendered = prepared.sql_rendered
        count_sql = prepared.count_sql

        assert_read_only_sql_statement(sql, context="Compiled SQL statement")
        if count_sql:
            assert_read_only_sql_statement(count_sql, context="Compiled count SQL statement")

        resp = ctx.sql_exec.submit_statement_async(
            sql,
            params,
        )

        statement_id = resp.get("statement_id")
        if not statement_id:
            raise ServiceError("Databricks did not return statement_id", status_code=500)

        job_id = uuid.uuid4().hex
        _put_job(
            job_id,
            {
                "workspace_id": workspace_id,
                "statement_id": statement_id,
                "kind": kind,
                "sql": sql,
                "params": params,
                "sqlRendered": sql_rendered,
                "limit": limit,
                "offset": offset,
                "countSql": count_sql,
                "sqlJson": sql_json,
            },
        )

        return {"jobId": job_id, "statementId": statement_id}, 200

    def status(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = _get_job(job_id)
        if not job or job.get("workspace_id") != workspace_id:
            raise ServiceError("Execution job not found", status_code=404)

        ctx = self._builder.build(workspace_id)
        status = ctx.sql_exec.get_statement_status(job["statement_id"])
        state = (status.get("status") or {}).get("state") or status.get("status")

        return {
            "jobId": job_id,
            "statementId": job["statement_id"],
            "status": state,
            "raw": status,
        }, 200

    def cancel(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = _get_job(job_id)
        if not job or job.get("workspace_id") != workspace_id:
            raise ServiceError("Execution job not found", status_code=404)

        ctx = self._builder.build(workspace_id)
        ctx.sql_exec.cancel_statement(job["statement_id"])

        return {"ok": True}, 200

    def results(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = _get_job(job_id)
        if not job or job.get("workspace_id") != workspace_id:
            raise ServiceError("Execution job not found", status_code=404)

        ctx = self._builder.build(workspace_id)
        status = ctx.sql_exec.get_statement_status(job["statement_id"])
        state = (status.get("status") or {}).get("state") or status.get("status")
        state = str(state or "").upper()

        if state in {"PENDING", "RUNNING", "QUEUED"}:
            return {
                "error": "Execution still running",
                "status": state,
                "jobId": job_id,
                "statementId": job["statement_id"],
            }, 409
        if state not in {"SUCCEEDED"}:
            return {
                "error": f"Execution {state.lower() or 'failed'}",
                "status": state or "FAILED",
                "jobId": job_id,
                "statementId": job["statement_id"],
            }, 500

        rows_any = ctx.sql_exec.fetch_all_json(job["statement_id"])
        columns = _columns_from_manifest(status.get("manifest")) or _columns_from_rows(rows_any)
        rows = _rows_to_dicts(rows_any, columns)

        total = None
        count_sql = job.get("countSql") or job.get("count_sql")
        if count_sql:
            assert_read_only_sql_statement(str(count_sql), context="Stored count SQL statement")
            count_resp = ctx.sql_exec.submit_statement(count_sql, parameters=job.get("params") or {})
            total = _extract_total((count_resp or {}).get("rows") or [])
        if total is None:
            result = status.get("result") or {}
            total = result.get("row_count") or result.get("rowcount") or status.get("rowcount")
        if total is None:
            total = len(rows)

        return {
            "sql": job.get("sql"),
            "sqlRendered": job.get("sqlRendered"),
            "params": job.get("params") or {},
            "rows": rows,
            "columns": columns,
            "total": total,
            "totalRowCount": total,
            "limit": job.get("limit"),
            "offset": job.get("offset"),
        }, 200
