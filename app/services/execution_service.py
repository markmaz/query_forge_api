from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import valkey

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import VALKEY_ADDRESS, VALKEY_PORT
from app.exceptions.forge_error import ForgeError
from app.services.execution import (
    ExecutionJobService,
    ExecutionModeQueryBuilder,
    ExecutionModeQueryBuilderSql,
    ExecutionRequestValidator,
    build_assistant_result_message,
    normalize_status_dict,
    utc_now_iso,
)
from app.services.execution.execution_result_formatter import (
    columns_from_manifest,
    columns_from_rows,
    exec_rows_to_dicts,
    extract_total,
)
from app.services.domain_resolver import DomainResolver
from app.services.analytics.executor_adapter import AnalyticsExecutorForgeAdapter
from app.ports.sql_executor_abc import SQLExecutor
from app.services.query_forge.service import QueryForgeService
from app.services.sql_guard_service import assert_no_disallowed_client_sql_fields, assert_read_only_sql_statement
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

logger = logging.getLogger(__name__)

_JOB_TTL_S = 30 * 60
_valkey_client: Optional[valkey.StrictValkey] = None


def _get_valkey_client() -> valkey.StrictValkey:
    global _valkey_client
    if _valkey_client is None:
        _valkey_client = valkey.StrictValkey(
            host=VALKEY_ADDRESS,
            port=VALKEY_PORT,
            decode_responses=True,
        )
    return _valkey_client


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return ExecutionJobService(
        client_factory=_get_valkey_client,
        utc_now_iso=utc_now_iso,
        ttl_s=_JOB_TTL_S,
    ).get_job(job_id)


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


def _build_assistant_result_message(
    *,
    rows: list[Dict[str, Any]],
    columns: list[Dict[str, Any]],
    total: Any,
    limit: Any,
    offset: Any,
) -> Dict[str, Any]:
    return build_assistant_result_message(
        rows=rows,
        columns=columns,
        total=total,
        limit=limit,
        offset=offset,
    )


class QueryForgeMetadataSQLExecutor(SQLExecutor):
    """Read-only analytics executor for QueryForge-owned reporting read models."""

    def __init__(self, *, sql: Optional[ForgeMetaSQL] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def execute(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        assert_read_only_sql_statement(sql, context="Metadata reporting SQL statement")
        return self._sql.execute_query_mappings(sql, params or {})

    def test_connection(self) -> None:
        self._sql.execute_query_mappings("SELECT 1 AS ok", {})

    def get_dialect(self) -> str:
        return "mysql"


def _build_metadata_sql_exec() -> AnalyticsExecutorForgeAdapter:
    return AnalyticsExecutorForgeAdapter(QueryForgeMetadataSQLExecutor())


def _sql_json_domain_id(sql_json: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(sql_json, dict):
        return None
    for key in ("domainId", "domain_id", "baseDomainId", "base_domain_id"):
        value = sql_json.get(key)
        if value is None:
            continue
        try:
            domain_id = int(value)
        except (TypeError, ValueError):
            return None
        return domain_id if domain_id > 0 else None
    return None


def _sql_json_uses_flowforge_metadata_domain(*, workspace_id: str, sql_json: Optional[Dict[str, Any]]) -> bool:
    domain_id = _sql_json_domain_id(sql_json)
    if domain_id is None:
        return False
    rows = ForgeMetaSQL().execute_query_mappings(
        """
        SELECT d.id
        FROM domain d
        LEFT JOIN domain_workspace_table dwt
          ON dwt.domain_id = d.id
        LEFT JOIN workspace_table wt
          ON wt.id = dwt.workspace_table_id
        WHERE d.workspace_id = :workspace_id
          AND d.id = :domain_id
          AND (
            d.kind = 'workflow_intelligence'
            OR wt.origin = 'FLOWFORGE'
          )
        LIMIT 1
        """,
        {"workspace_id": workspace_id, "domain_id": domain_id},
    )
    return bool(rows)


class ExecutionService:
    def __init__(self, context_builder: Optional[WorkspaceSqlContextBuilder] = None):
        self._builder = context_builder or WorkspaceSqlContextBuilder()
        self._job_service = ExecutionJobService(
            client_factory=_get_valkey_client,
            utc_now_iso=utc_now_iso,
            ttl_s=_JOB_TTL_S,
        )
        self._validator = ExecutionRequestValidator(
            assert_no_disallowed_client_sql_fields=assert_no_disallowed_client_sql_fields,
            int_from_payload=_qf_int_from_payload,
            int_from_args=_qf_int_from_args,
        )
        self._query_builder_mode = ExecutionModeQueryBuilder(
            query_forge_service_cls=QueryForgeService,
            domain_resolver_factory=lambda workspace_id: DomainResolver(workspace_id=workspace_id),
        )
        self._query_builder_sql_mode = ExecutionModeQueryBuilderSql()

    def start(self, workspace_id: str, payload: Dict[str, Any], query_args: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
        request = self._validator.validate_start(payload, query_args)
        uses_metadata_backend = request.kind == "query_builder" and _sql_json_uses_flowforge_metadata_domain(
            workspace_id=workspace_id,
            sql_json=request.sql_json,
        )
        execution_backend = "workspace"
        if uses_metadata_backend:
            sql_exec = _build_metadata_sql_exec()
            execution_backend = "queryforge_metadata"
        else:
            ctx = self._builder.build(workspace_id)
            sql_exec = ctx.sql_exec
        if request.kind == "query_builder_sql":
            prepared = self._query_builder_sql_mode.prepare(raw_sql=str(request.raw_sql or ""))
        else:
            prepared = self._query_builder_mode.prepare(
                workspace_id=workspace_id,
                sql_exec=sql_exec,
                sql_json=request.sql_json or {},
                mode=(query_args.get("mode") or "preview").strip().lower(),
                limit=request.limit,
                offset=request.offset,
            )

        assert_read_only_sql_statement(
            prepared.sql,
            context="Provided SQL statement" if request.kind == "query_builder_sql" else "Compiled SQL statement",
        )
        if prepared.count_sql:
            assert_read_only_sql_statement(prepared.count_sql, context="Compiled count SQL statement")

        resp = sql_exec.submit_statement_async(
            prepared.sql,
            prepared.params,
        )

        statement_id = resp.get("statement_id") or resp.get("qf_statement_id")
        if not statement_id:
            raise ForgeError("Execution backend did not return statement_id", status_code=500)

        inline_status: Optional[Dict[str, Any]] = None
        inline_rows: Optional[List[Any]] = None
        inline_total: Optional[int] = None
        if isinstance(sql_exec, AnalyticsExecutorForgeAdapter):
            inline_status = normalize_status_dict(resp.get("status"))
            if isinstance(inline_status, dict):
                state = str(inline_status.get("state") or "").strip().upper()
                if state == "SUCCEEDED":
                    try:
                        inline_rows = sql_exec.fetch_all_json(str(statement_id))
                    except (OSError, RuntimeError, TypeError, ValueError):
                        inline_rows = None
                    if prepared.count_sql:
                        try:
                            count_resp = sql_exec.submit_statement(prepared.count_sql, parameters=prepared.params)
                            inline_total = extract_total((count_resp or {}).get("rows") or [])
                        except (OSError, RuntimeError, TypeError, ValueError):
                            inline_total = None

        job_id = self._job_service.create_job(
            {
                "workspace_id": workspace_id,
                "statement_id": statement_id,
                "kind": request.kind,
                "execution_backend": execution_backend,
                "sql": prepared.sql,
                "params": prepared.params,
                "sqlRendered": prepared.sql_rendered,
                "limit": request.limit,
                "offset": request.offset,
                "countSql": prepared.count_sql,
                "sqlJson": request.sql_json,
                "inline_status": inline_status,
                "inline_rows": inline_rows,
                "inline_total": inline_total,
            },
        )

        return {"jobId": job_id, "statementId": statement_id}, 200

    def status(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = self._job_service.get_job_for_workspace(workspace_id, job_id)

        inline_status = normalize_status_dict(job.get("inline_status"))
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

        if str(state or "").upper() == "FAILED":
            error = (status.get("status") or {}).get("error") or {}
            error_code = error.get("error_code", "UNKNOWN")
            error_message = error.get("message", "No message returned")
            logger.warning(
                "Databricks statement failed: job_id=%s statement_id=%s error_code=%s message=%s sql=%s",
                job_id,
                job["statement_id"],
                error_code,
                error_message,
                job.get("sql"),
            )

        return {
            "jobId": job_id,
            "statementId": job["statement_id"],
            "status": state,
            "raw": status,
        }, 200

    def cancel(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = self._job_service.get_job_for_workspace(workspace_id, job_id)

        ctx = self._builder.build(workspace_id)
        ctx.sql_exec.cancel_statement(job["statement_id"])

        return {"ok": True}, 200

    def results(self, workspace_id: str, job_id: str) -> tuple[Dict[str, Any], int]:
        job = self._job_service.get_job_for_workspace(workspace_id, job_id)

        ctx = None
        inline_status = normalize_status_dict(job.get("inline_status"))
        if isinstance(inline_status, dict):
            status = {"status": inline_status}
        else:
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
            if ctx is None:
                ctx = self._builder.build(workspace_id)
            qf_rows_any = ctx.sql_exec.fetch_all_json(job["statement_id"])
        columns = columns_from_manifest(status.get("manifest")) or columns_from_rows(qf_rows_any)
        rows = exec_rows_to_dicts(qf_rows_any, columns)

        total = job.get("inline_total")
        try:
            total = int(total) if total is not None else None
        except (TypeError, ValueError):
            total = None
        qf_count_sql = job.get("countSql") or job.get("qf_count_sql")
        if total is None and qf_count_sql:
            assert_read_only_sql_statement(str(qf_count_sql), context="Stored count SQL statement")
            if ctx is None:
                ctx = self._builder.build(workspace_id)
            count_resp = ctx.sql_exec.submit_statement(qf_count_sql, parameters=job.get("params") or {})
            total = extract_total((count_resp or {}).get("rows") or [])
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
