from __future__ import annotations

import io
from dataclasses import dataclass

import pyarrow as pa
from openpyxl import Workbook

from app.exceptions.forge_error import ForgeError
from app.services.sql_guard_service import assert_read_only_sql_statement


def table_to_excel_bytes(table: pa.Table) -> bytes:
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


@dataclass(frozen=True)
class ExportDownloadResult:
    filename: str
    content: bytes


class ExportMaterializationService:
    def __init__(self, *, workspace_context_builder, token_store) -> None:
        self._workspace_context_builder = workspace_context_builder
        self._token_store = token_store

    def build_excel_download(self, *, workspace_id: str, token: str) -> ExportDownloadResult:
        payload = self._token_store.pop_export_job(token)
        if not payload:
            raise ForgeError("Export not found", status_code=404)
        if payload.get("workspace_id") != workspace_id:
            raise ForgeError("Export not found", status_code=404)

        sql = payload.get("sql")
        params = payload.get("params") or {}
        filename = payload.get("filename") or "export.xlsx"
        if not isinstance(sql, str):
            raise ForgeError("Export not available", status_code=404)
        if params and not isinstance(params, dict):
            raise ForgeError("Export not available", status_code=404)

        assert_read_only_sql_statement(sql, context="Stored export SQL statement")

        ctx = self._workspace_context_builder.build(workspace_id)
        data_resp = ctx.sql_exec.submit_statement(
            sql,
            parameters=params,
            qf_result_fmt="ARROW_STREAM",
        )
        table = data_resp.get("table")
        if not isinstance(table, pa.Table):
            raise ForgeError("Failed to fetch export rows", status_code=500)

        return ExportDownloadResult(filename=filename, content=table_to_excel_bytes(table))
