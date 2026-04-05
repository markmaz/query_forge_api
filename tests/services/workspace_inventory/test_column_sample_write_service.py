from __future__ import annotations

from typing import Any, Dict, List, Optional

import pyarrow as pa

from app.services.workspace_inventory.column_sample_write_service import ColumnSampleWriteService, _quote_col, _quote_uc_ident
from tests._support.fakes import FakeDatabricksForgeQueryPort, FakeForgeQueryPort


class _SampleService(ColumnSampleWriteService):
    def _fetch_column_stats(self, *, full_name: str, column_name: str, timeout_s: Optional[int] = 120, qf_timeout_s: Optional[int] = None) -> Dict[str, Any]:
        del full_name, column_name, timeout_s, qf_timeout_s
        return {"sample_row_count": 10, "null_count": 1, "null_pct": 0.1, "approx_distinct": 2}

    def _fetch_column_samples(
        self,
        *,
        full_name: str,
        column_name: str,
        limit: int = 10,
        timeout_s: Optional[int] = 120,
        qf_timeout_s: Optional[int] = None,
        distinct: bool = True,
        **_kwargs: Any,
    ) -> List[str]:
        del full_name, column_name, limit, timeout_s, qf_timeout_s, distinct
        return ["a", "b"]


class _FailingSampleService(_SampleService):
    def _fetch_column_stats(self, *, full_name: str, column_name: str, timeout_s: Optional[int] = 120, qf_timeout_s: Optional[int] = None) -> Dict[str, Any]:
        del full_name, column_name, timeout_s, qf_timeout_s
        raise RuntimeError("boom")


def test_quote_uc_ident() -> None:
    assert _quote_uc_ident("main.asset.table") == "`main`.`asset`.`table`"
    assert _quote_uc_ident("just_table") == "just_table"


def test_quote_col() -> None:
    assert _quote_col("col") == "`col`"
    assert _quote_col("bad`col") == "`bad``col`"


def test_fetch_column_stats_and_samples() -> None:
    sql = FakeDatabricksForgeQueryPort()
    sql.submit_responses.append(
        {"table": pa.Table.from_pylist([{"sample_row_count": 10, "null_count": 2, "approx_distinct_count": 3}])}
    )
    sql.submit_responses.append(
        {"table": pa.Table.from_pylist([{"value": "alpha", "n": 2}, {"value": "beta", "n": 1}])}
    )
    svc = ColumnSampleWriteService(sql=sql, mysql=FakeForgeQueryPort())

    stats = svc._fetch_column_stats(full_name="main.asset.table", column_name="col")
    samples = svc._fetch_column_samples(full_name="main.asset.table", column_name="col", limit=5)

    assert stats["sample_row_count"] == 10
    assert samples == ["alpha", "beta"]


def test_refresh_model_samples_success() -> None:
    mysql = FakeForgeQueryPort()
    mysql.query_mappings_responses.append([{"workspace_table_id": 1, "full_name": "main.asset.patients"}])
    mysql.query_mappings_responses.append([{"id": 10, "column_name": "patient_id", "data_type": "STRING", "nullable": 1, "is_active": 1}])

    svc = _SampleService(sql=FakeDatabricksForgeQueryPort(), mysql=mysql)
    result = svc.refresh_model_samples(workspace_id="ws-1", schema_name="asset")

    assert result["columns_updated"] == 1
    update_call = next(call for call in mysql.write_calls if "UPDATE workspace_column" in call.query)
    assert update_call.params["id"] == 10


def test_refresh_model_samples_handles_failures() -> None:
    mysql = FakeForgeQueryPort()
    mysql.query_mappings_responses.append([{"workspace_table_id": 1, "full_name": "main.asset.patients"}])
    mysql.query_mappings_responses.append([{"id": 10, "column_name": "patient_id", "data_type": "STRING", "nullable": 1, "is_active": 1}])

    svc = _FailingSampleService(sql=FakeDatabricksForgeQueryPort(), mysql=mysql)
    result = svc.refresh_model_samples(workspace_id="ws-1", schema_name="asset")

    assert result["columns_failed"] == 1
