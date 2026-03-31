from __future__ import annotations

from app.services.exports.export_policy import QF_EXCEL_MAX_ROWS, build_qf_export_policy
from app.services.exports.export_request_service import ExportRequestService
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
    def __init__(self, total: int):
        self.total = total

    def submit_statement(self, sql: str, parameters=None, qf_result_fmt=None):
        return {"rows": [{"total": self.total}]}


class _Ctx:
    def __init__(self, total: int):
        self.sql_exec = _SqlExec(total)


class _Builder:
    def __init__(self, total: int):
        self._total = total

    def build(self, workspace_id: str):
        return _Ctx(self._total)


class _Compiled:
    sql = "SELECT 1"
    params = {}
    qf_count_sql = "SELECT COUNT(*) AS total FROM t"


class _NoCodeService:
    def __init__(self, executor, domain_resolver):
        self.executor = executor
        self.domain_resolver = domain_resolver

    def normalize(self, sql_json):
        return sql_json

    def compile(self, normalized, mode="export", limit=0, offset=0):
        return _Compiled()


def test_prepare_excel_export_blocks_over_limit() -> None:
    client = _DummyClient()
    service = ExportRequestService(
        workspace_context_builder=_Builder(QF_EXCEL_MAX_ROWS + 2),
        query_forge_service_cls=_NoCodeService,
        domain_resolver_factory=lambda workspace_id: object(),
        token_store=ExportTokenStore(client_factory=lambda: client),
        fetch_cached_rowcount=lambda signature: None,
        store_cached_rowcount=lambda signature, total_rows: None,
        build_export_policy=build_qf_export_policy,
        rowcount_signature=lambda sql, params: "sig",
        excel_max_rows=QF_EXCEL_MAX_ROWS,
    )
    res = service.prepare_excel_export(workspace_id="ws1", payload={"sqlJson": {"domainId": 1}})
    assert res["error"] == "EXCEL_ROW_LIMIT"


def test_prepare_excel_export_allows_under_limit() -> None:
    client = _DummyClient()
    service = ExportRequestService(
        workspace_context_builder=_Builder(2),
        query_forge_service_cls=_NoCodeService,
        domain_resolver_factory=lambda workspace_id: object(),
        token_store=ExportTokenStore(client_factory=lambda: client),
        fetch_cached_rowcount=lambda signature: None,
        store_cached_rowcount=lambda signature, total_rows: None,
        build_export_policy=build_qf_export_policy,
        rowcount_signature=lambda sql, params: "sig",
        excel_max_rows=QF_EXCEL_MAX_ROWS,
    )
    res = service.prepare_excel_export(workspace_id="ws1", payload={"sqlJson": {"domainId": 1}})
    assert res["token"]
    assert res["filename"].endswith(".xlsx")
