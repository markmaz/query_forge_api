from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any, Dict, Optional

import valkey

from app.config import VALKEY_ADDRESS, VALKEY_PORT
from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainResolver
from app.services.analytics.executor_adapter import AnalyticsExecutorForgeAdapter
from app.services.query_forge_service import QueryForgeService
from app.services.sql_guard_service import assert_no_disallowed_client_sql_fields, assert_read_only_sql_statement
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

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


def _qf_job_key(job_id: str) -> str:
    return f"qf:exec:{job_id}"


def _put_job(job_id: str, payload: Dict[str, Any]) -> None:
    payload = dict(payload)
    payload.setdefault("created_at", _utc_now_iso())
    data = json.dumps(payload, default=str)
    _get_valkey_client().setex(_qf_job_key(job_id), _JOB_TTL_S, data)


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    data = _get_valkey_client().get(_qf_job_key(job_id))
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


def _qf_exec_rows_to_dicts(qf_rows_any: list[Any], columns: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not qf_rows_any:
        return []
    if qf_rows_any and isinstance(qf_rows_any[0], dict):
        return qf_rows_any
    if not columns:
        return []
    keys = [c.get("key") for c in columns]
    out: list[Dict[str, Any]] = []
    for row in qf_rows_any:
        if not isinstance(row, (list, tuple)):
            continue
        out.append({keys[i]: (row[i] if i < len(row) else None) for i in range(len(keys))})
    return out


def _qf_int_from_payload(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400)


def _qf_int_from_args(args: Dict[str, Any], name: str, default: int) -> int:
    raw = (args.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400)


def _qf_exec_extract_total(count_rows: list[Any]) -> Optional[int]:
    """Extract total row count from a COUNT(*) result. Returns None if not determinable."""
    if not count_rows:
        return None
    first = count_rows[0]
    if isinstance(first, dict) and first:
        # Try "total" first, then any first column value
        val = first.get("total") if "total" in first else next(iter(first.values()), None)
        try:
            return int(val)
        except (TypeError, ValueError):
            return None
    if isinstance(first, (list, tuple)) and len(first) >= 1:
        try:
            return int(first[0])
        except (TypeError, ValueError):
            return None
    return None


def _normalize_status_dict(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        out = dict(raw)
        if isinstance(out.get("status"), dict):
            status = dict(out.get("status") or {})
            if "state" in status or "error" in status:
                return status
        if "state" in out or "error" in out:
            return out
    if isinstance(raw, str) and raw.strip():
        return {"state": raw.strip()}
    return None


def _truncate_cell_value(value: Any, *, max_len: int = 80) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1]}…"


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _rows_markdown(columns: list[Dict[str, Any]], rows: list[Dict[str, Any]], *, max_rows: int = 10) -> str:
    if not columns or not rows:
        return ""
    col_keys = [str(col.get("key") or "").strip() for col in columns if str(col.get("key") or "").strip()]
    if not col_keys:
        return ""
    sample = rows[: max(1, int(max_rows))]
    header = "| " + " | ".join(_escape_markdown_cell(k) for k in col_keys) + " |"
    divider = "| " + " | ".join("---" for _ in col_keys) + " |"
    body_lines = []
    for row in sample:
        values = []
        for key in col_keys:
            raw = row.get(key) if isinstance(row, dict) else None
            values.append(_escape_markdown_cell(_truncate_cell_value(raw)))
        body_lines.append("| " + " | ".join(values) + " |")
    return "\n".join([header, divider, *body_lines])


def _build_assistant_result_message(
    *,
    rows: list[Dict[str, Any]],
    columns: list[Dict[str, Any]],
    total: Any,
    limit: Any,
    offset: Any,
) -> Dict[str, Any]:
    shown = len(rows)
    total_int = None
    try:
        total_int = int(total)
    except Exception:
        total_int = None
    summary = f"Query complete. Returned {shown} row(s)"
    if total_int is not None:
        summary += f" (total {total_int})"
    if limit is not None or offset is not None:
        summary += f". Limit={limit if limit is not None else 'n/a'}, Offset={offset if offset is not None else 'n/a'}"
    summary += "."
    table_md = _rows_markdown(columns, rows)
    content = summary if table_md == "" else f"{summary}\n\n{table_md}"
    return {
        "role": "assistant",
        "content": content,
        "format": "markdown",
        "kind": "execution_result",
    }


class ExecutionService:
    def __init__(self, context_builder: Optional[WorkspaceSqlContextBuilder] = None):
        self._builder = context_builder or WorkspaceSqlContextBuilder()

    def start(self, workspace_id: str, payload: Dict[str, Any], query_args: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
        assert_no_disallowed_client_sql_fields(payload)

        qf_sql_json = payload.get("sqlJson") or payload.get("sql_json")
        if qf_sql_json is None:
            raise ForgeError("sqlJson is required", status_code=400)
        if qf_sql_json is not None and not isinstance(qf_sql_json, dict):
            raise ForgeError("sqlJson must be an object", status_code=400)

        sql = ""
        params: Dict[str, Any] = {}

        kind = (payload.get("kind") or "").strip()
        if not kind and isinstance(qf_sql_json, dict):
            kind = "query_builder"
        if kind != "query_builder":
            raise ForgeError("kind must be query_builder", status_code=400)

        ctx = self._builder.build(workspace_id)
        qf_limit_raw = _qf_int_from_payload(payload.get("limit"), "limit")
        offset_raw = _qf_int_from_payload(payload.get("offset"), "offset")
        limit = qf_limit_raw if qf_limit_raw is not None else _qf_int_from_args(query_args, "limit", 200)
        offset = offset_raw if offset_raw is not None else _qf_int_from_args(query_args, "offset", 0)

        qf_rendered_sql = None
        qf_count_sql = None
        domain_resolver = DomainResolver(workspace_id=workspace_id)
        svc = QueryForgeService(executor=ctx.sql_exec, domain_resolver=domain_resolver)
        mode = (query_args.get("mode") or "preview").strip().lower()
        prepared = svc.prepare(raw_query=qf_sql_json, mode=mode, limit=limit, offset=offset)
        sql = prepared.sql
        params = prepared.params
        qf_rendered_sql = prepared.qf_rendered_sql
        qf_count_sql = prepared.qf_count_sql

        assert_read_only_sql_statement(sql, context="Compiled SQL statement")
        if qf_count_sql:
            assert_read_only_sql_statement(qf_count_sql, context="Compiled count SQL statement")

        resp = ctx.sql_exec.submit_statement_async(
            sql,
            params,
        )

        statement_id = resp.get("statement_id") or resp.get("qf_statement_id")
        if not statement_id:
            raise ForgeError("Databricks did not return statement_id", status_code=500)

        inline_status: Optional[Dict[str, Any]] = None
        inline_rows: Optional[List[Any]] = None
        if isinstance(ctx.sql_exec, AnalyticsExecutorForgeAdapter):
            inline_status = _normalize_status_dict(resp.get("status"))
            if isinstance(inline_status, dict):
                state = str(inline_status.get("state") or "").strip().upper()
                if state == "SUCCEEDED":
                    try:
                        inline_rows = ctx.sql_exec.fetch_all_json(str(statement_id))
                    except Exception:
                        inline_rows = None

        job_id = uuid.uuid4().hex
        _put_job(
            job_id,
            {
                "workspace_id": workspace_id,
                "statement_id": statement_id,
                "kind": kind,
                "sql": sql,
                "params": params,
                "sqlRendered": qf_rendered_sql,
                "limit": limit,
                "offset": offset,
                "countSql": qf_count_sql,
                "sqlJson": qf_sql_json,
                "inline_status": inline_status,
                "inline_rows": inline_rows,
            },
        )

        return {"jobId": job_id, "statementId": statement_id}, 200

    def status(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = _get_job(job_id)
        if not job or job.get("workspace_id") != workspace_id:
            raise ForgeError("Execution job not found", status_code=404)

        inline_status = _normalize_status_dict(job.get("inline_status"))
        if isinstance(inline_status, dict):
            state = inline_status.get("state") or inline_status.get("status")
            return {
                "jobId": job_id,
                "statementId": job["statement_id"],
                "status": state,
                "raw": {"status": inline_status},
            }, 200

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
            raise ForgeError("Execution job not found", status_code=404)

        ctx = self._builder.build(workspace_id)
        ctx.sql_exec.cancel_statement(job["statement_id"])

        return {"ok": True}, 200

    def results(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = _get_job(job_id)
        if not job or job.get("workspace_id") != workspace_id:
            raise ForgeError("Execution job not found", status_code=404)

        ctx = self._builder.build(workspace_id)
        inline_status = _normalize_status_dict(job.get("inline_status"))
        if isinstance(inline_status, dict):
            status = {"status": inline_status}
        else:
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
            error_text = str((status.get("status") or {}).get("error") or "").strip()
            error_message = f"Execution {state.lower() or 'failed'}"
            if error_text:
                error_message = f"{error_message}: {error_text}"
            return {
                "error": error_message,
                "status": state or "FAILED",
                "jobId": job_id,
                "statementId": job["statement_id"],
            }, 500

        inline_rows = job.get("inline_rows")
        if isinstance(inline_rows, list):
            qf_rows_any = list(inline_rows)
        else:
            qf_rows_any = ctx.sql_exec.fetch_all_json(job["statement_id"])
        columns = _columns_from_manifest(status.get("manifest")) or _columns_from_rows(qf_rows_any)
        rows = _qf_exec_rows_to_dicts(qf_rows_any, columns)

        total = None
        qf_count_sql = job.get("countSql") or job.get("qf_count_sql")
        if qf_count_sql:
            assert_read_only_sql_statement(str(qf_count_sql), context="Stored count SQL statement")
            count_resp = ctx.sql_exec.submit_statement(qf_count_sql, parameters=job.get("params") or {})
            total = _qf_exec_extract_total((count_resp or {}).get("rows") or [])
        if total is None:
            result = status.get("result") or {}
            raw_total = result.get("row_count") or result.get("rowcount") or status.get("rowcount")
            try:
                total = int(raw_total) if raw_total is not None else None
            except (TypeError, ValueError):
                total = None
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
            "assistant_message": _build_assistant_result_message(
                rows=rows,
                columns=columns,
                total=total,
                limit=job.get("limit"),
                offset=job.get("offset"),
            ),
        }, 200
