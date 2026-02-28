from __future__ import annotations

import io
import json
import logging
import uuid
from typing import Any, List, Optional

import pyarrow as pa
import valkey
from flask import request, send_file
from flask_restx import Namespace, Resource
from openpyxl import Workbook

from app.config import VALKEY_ADDRESS, VALKEY_PORT
from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_workspace_id_from_header
from app.services.domain_resolver import DomainResolver
from app.services.exports.export_policy import (
    EXCEL_MAX_ROWS,
    build_export_policy,
    get_cached_rowcount,
    make_rowcount_signature,
    set_cached_rowcount,
)
from app.services.no_code_query_service import NoCodeQueryService
from app.services.sql_guard_service import assert_no_disallowed_client_sql_fields, assert_read_only_sql_statement
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder

logger = logging.getLogger(__name__)
exports_ns = Namespace("exports", description="Exports")
_EXPORT_TOKEN_TTL_S = 300
_valkey_client: Optional[valkey.StrictValkey] = None


def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400


def _extract_total(count_rows: List[Any]) -> int:
    if not count_rows:
        return 0
    first = count_rows[0]
    if isinstance(first, dict):
        return int(first.get("total") or 0)
    if isinstance(first, (list, tuple)) and len(first) >= 1:
        return int(first[0] or 0)
    return 0


def _get_valkey_client() -> valkey.StrictValkey:
    global _valkey_client
    if _valkey_client is None:
        _valkey_client = valkey.StrictValkey(
            host=VALKEY_ADDRESS,
            port=VALKEY_PORT,
            decode_responses=True,
        )
    return _valkey_client


def _set_export_job(payload: dict[str, Any]) -> str:
    token = uuid.uuid4().hex
    key = f"export:excel:{token}"
    data = json.dumps(payload, default=str)
    _get_valkey_client().setex(key, _EXPORT_TOKEN_TTL_S, data)
    return token


def _pop_export_job(token: str) -> Optional[dict[str, Any]]:
    key = f"export:excel:{token}"
    client = _get_valkey_client()
    data = client.get(key)
    if not data:
        return None
    client.delete(key)
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    return payload


def _table_to_excel_bytes(table: pa.Table) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title="Export")
    columns = list(table.schema.names)
    sheet.append(columns)

    for batch in table.to_batches(max_chunksize=5000):
        rows = batch.to_pylist()
        for row in rows:
            sheet.append([row.get(col) for col in columns])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.read()


@exports_ns.route("/excel")
class ExcelExport(Resource):
    @token_required
    def post(self):
        try:
            workspace_id = get_workspace_id_from_header()
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            signature = (payload.get("signature") or "").strip() or None
            total_rows = get_cached_rowcount(signature) if signature else None

            assert_no_disallowed_client_sql_fields(payload)

            sql_json = payload.get("sqlJson") or payload.get("sql_json")
            if sql_json is None:
                raise ServiceError("sqlJson is required", status_code=400)
            if not isinstance(sql_json, dict):
                raise ServiceError("sqlJson must be an object", status_code=400)

            ctx = WorkspaceContextBuilder().build(workspace_id)
            domain_resolver = DomainResolver(workspace_id=workspace_id)
            svc = NoCodeQueryService(executor=ctx.sql_exec, domain_resolver=domain_resolver)
            normalized = svc.normalize(sql_json)
            compiled = svc.compile(normalized, mode="export", limit=0, offset=0)
            sql = compiled.sql
            params = compiled.params or {}
            count_sql = compiled.count_sql

            if not isinstance(sql, str):
                raise ServiceError("sql must be a string", status_code=400)
            if params and not isinstance(params, dict):
                raise ServiceError("Compiled params must be an object", status_code=500)

            assert_read_only_sql_statement(sql, context="Compiled SQL statement")
            if not count_sql:
                count_sql = f"SELECT COUNT(*) AS total FROM (\n{sql}\n) q"
            assert_read_only_sql_statement(str(count_sql), context="Compiled count SQL statement")

            signature = signature or make_rowcount_signature(sql, params)

            if total_rows is None:
                count_resp = ctx.sql_exec.submit_statement(count_sql, parameters=params)
                total_rows = _extract_total((count_resp or {}).get("rows") or [])
                set_cached_rowcount(signature, total_rows)

            policy = build_export_policy(int(total_rows or 0))
            if not policy["excel"]["allowed"]:
                return {
                    "error": "EXCEL_ROW_LIMIT",
                    "rowCount": int(total_rows or 0),
                    "maxRows": EXCEL_MAX_ROWS,
                    "message": "Result set exceeds Excel row limit.",
                }, 409

            filename = (payload.get("fileName") or "export").strip()
            if not filename.lower().endswith(".xlsx"):
                filename = f"{filename}.xlsx"

            token = _set_export_job(
                {
                    "workspace_id": workspace_id,
                    "sql": sql,
                    "params": params,
                    "filename": filename,
                }
            )
            return {
                "token": token,
                "filename": filename,
            }, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Excel export failed")
            return {"error": "Excel export failed"}, 500


@exports_ns.route("/excel/<string:token>")
class ExcelDownload(Resource):
    @token_required
    def get(self, token: str):
        try:
            workspace_id = get_workspace_id_from_header()
            payload = _pop_export_job(token)
            if not payload:
                raise ServiceError("Export not found", status_code=404)
            if payload.get("workspace_id") != workspace_id:
                raise ServiceError("Export not found", status_code=404)

            sql = payload.get("sql")
            params = payload.get("params") or {}
            filename = payload.get("filename") or "export.xlsx"
            if not isinstance(sql, str):
                raise ServiceError("Export not available", status_code=404)
            if params and not isinstance(params, dict):
                raise ServiceError("Export not available", status_code=404)

            assert_read_only_sql_statement(sql, context="Stored export SQL statement")

            ctx = WorkspaceContextBuilder().build(workspace_id)
            data_resp = ctx.sql_exec.submit_statement(
                sql,
                parameters=params,
                result_format="ARROW_STREAM",
            )
            table = data_resp.get("table")
            if not isinstance(table, pa.Table):
                raise ServiceError("Failed to fetch export rows", status_code=500)

            xlsx_bytes = _table_to_excel_bytes(table)
            return send_file(
                io.BytesIO(xlsx_bytes),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=filename,
                max_age=0,
            )
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Excel download failed")
            return {"error": "Excel download failed"}, 500
