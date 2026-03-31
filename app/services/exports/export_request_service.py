from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.services.sql_guard_service import (
    assert_no_disallowed_client_sql_fields,
    assert_read_only_sql_statement,
)


def parse_export_count_result(count_rows: List[Any]) -> int:
    if not count_rows:
        return 0
    first = count_rows[0]
    if isinstance(first, dict):
        return int(first.get("total") or 0)
    if isinstance(first, (list, tuple)) and len(first) >= 1:
        return int(first[0] or 0)
    return 0


class ExportRequestService:
    def __init__(
        self,
        *,
        workspace_context_builder,
        query_forge_service_cls,
        domain_resolver_factory: Callable[[str], Any],
        token_store,
        fetch_cached_rowcount: Callable[[Optional[str]], Optional[int]],
        store_cached_rowcount: Callable[[str, int], None],
        build_export_policy: Callable[[int], Dict[str, Any]],
        rowcount_signature: Callable[[str, Dict[str, Any]], str],
        excel_max_rows: int,
    ) -> None:
        self._workspace_context_builder = workspace_context_builder
        self._query_forge_service_cls = query_forge_service_cls
        self._domain_resolver_factory = domain_resolver_factory
        self._token_store = token_store
        self._fetch_cached_rowcount = fetch_cached_rowcount
        self._store_cached_rowcount = store_cached_rowcount
        self._build_export_policy = build_export_policy
        self._rowcount_signature = rowcount_signature
        self._excel_max_rows = excel_max_rows

    def prepare_excel_export(self, *, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        signature = (payload.get("signature") or "").strip() or None
        total_rows = self._fetch_cached_rowcount(signature) if signature else None

        assert_no_disallowed_client_sql_fields(payload)

        sql_json = payload.get("sqlJson") or payload.get("sql_json")
        if sql_json is None:
            raise ForgeError("sqlJson is required", status_code=400)
        if not isinstance(sql_json, dict):
            raise ForgeError("sqlJson must be an object", status_code=400)

        ctx = self._workspace_context_builder.build(workspace_id)
        domain_resolver = self._domain_resolver_factory(workspace_id)
        svc = self._query_forge_service_cls(executor=ctx.sql_exec, domain_resolver=domain_resolver)
        normalized = svc.normalize(sql_json)
        compiled = svc.compile(normalized, mode="export", limit=0, offset=0)
        sql = compiled.sql
        params = compiled.params or {}
        qf_count_sql = compiled.qf_count_sql

        if not isinstance(sql, str):
            raise ForgeError("sql must be a string", status_code=400)
        if params and not isinstance(params, dict):
            raise ForgeError("Compiled params must be an object", status_code=500)

        assert_read_only_sql_statement(sql, context="Compiled SQL statement")
        if not qf_count_sql:
            qf_count_sql = f"SELECT COUNT(*) AS total FROM (\n{sql}\n) q"
        assert_read_only_sql_statement(str(qf_count_sql), context="Compiled count SQL statement")

        signature = signature or self._rowcount_signature(sql, params)
        if total_rows is None:
            count_resp = ctx.sql_exec.submit_statement(qf_count_sql, parameters=params)
            total_rows = parse_export_count_result((count_resp or {}).get("rows") or [])
            self._store_cached_rowcount(signature, total_rows)

        policy = self._build_export_policy(int(total_rows or 0))
        if not policy["excel"]["allowed"]:
            return {
                "error": "EXCEL_ROW_LIMIT",
                "rowCount": int(total_rows or 0),
                "maxRows": self._excel_max_rows,
                "message": "Result set exceeds Excel row limit.",
            }

        filename = (payload.get("fileName") or "export").strip()
        if not filename.lower().endswith(".xlsx"):
            filename = f"{filename}.xlsx"

        token = self._token_store.set_export_job(
            {
                "workspace_id": workspace_id,
                "sql": sql,
                "params": params,
                "filename": filename,
            }
        )
        return {"token": token, "filename": filename}
