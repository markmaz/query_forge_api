from __future__ import annotations

import pyarrow as pa

from app.services.exports.export_materialization_service import ExportMaterializationService
from app.services.exports.export_token_store import ExportTokenStore


class _DummyClient:
    def __init__(self):
        self._store = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    def get(self, key: str):
        return self._store.get(key)

    def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


class _SqlExec:
    def submit_statement(self, sql: str, parameters=None, qf_result_fmt=None):
        table = pa.Table.from_pylist([{"a": 1}, {"a": 2}])
        return {"table": table, "rows": table.to_pylist()}


class _Ctx:
    def __init__(self):
        self.sql_exec = _SqlExec()


class _Builder:
    def build(self, workspace_id: str):
        return _Ctx()


def test_build_excel_download() -> None:
    client = _DummyClient()
    store = ExportTokenStore(client_factory=lambda: client)
    token = store.set_export_job(
        {
            "workspace_id": "ws1",
            "sql": "SELECT 1",
            "params": {},
            "filename": "export.xlsx",
        }
    )
    service = ExportMaterializationService(workspace_context_builder=_Builder(), token_store=store)
    result = service.build_excel_download(workspace_id="ws1", token=token)
    assert result.filename == "export.xlsx"
    assert result.content
