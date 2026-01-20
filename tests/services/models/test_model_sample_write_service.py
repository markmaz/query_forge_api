from __future__ import annotations

from typing import Any, Dict, List, Optional

import pyarrow as pa

from app.services.models.model_sample_write_service import ModelSampleService, _quote_col, _quote_uc_ident
from tests._support.fakes import FakeDatabricksSQLExecutor, FakeSQLExecutor


class _SampleService(ModelSampleService):
    def _fetch_column_stats(self, *, full_name: str, column_name: str, timeout_s: Optional[int] = 120) -> Dict[str, Any]:
        return {"sample_row_count": 10, "null_count": 1, "null_pct": 0.1, "approx_distinct": 2}

    def _fetch_column_samples(
        self,
        *,
        full_name: str,
        column_name: str,
        limit: int = 25,
        timeout_s: Optional[int] = 120,
        **_kwargs: Any,
    ) -> List[str]:
        return ["a", "b"]


class _FailingSampleService(_SampleService):
    def _fetch_column_stats(self, *, full_name: str, column_name: str, timeout_s: Optional[int] = 120) -> Dict[str, Any]:
        raise RuntimeError("boom")


def test_quote_uc_ident() -> None:
    assert _quote_uc_ident("main.asset.table") == "`main`.`asset`.`table`"
    assert _quote_uc_ident("just_table") == "just_table"


def test_quote_col() -> None:
    assert _quote_col("col") == "`col`"
    assert _quote_col("bad`col") == "`bad``col`"


def test_fetch_column_stats_and_samples() -> None:
    sql = FakeDatabricksSQLExecutor()
    sql.submit_responses.append(
        {"table": pa.Table.from_pylist([{"sample_row_count": 10, "null_count": 2, "approx_distinct_count": 3}])}
    )
    sql.submit_responses.append(
        {"table": pa.Table.from_pylist([{"value": "alpha", "n": 2}, {"value": "beta", "n": 1}])}
    )
    svc = ModelSampleService(sql=sql, mysql=FakeSQLExecutor())

    stats = svc._fetch_column_stats(full_name="main.asset.table", column_name="col")
    samples = svc._fetch_column_samples(full_name="main.asset.table", column_name="col", limit=5)

    assert stats["sample_row_count"] == 10
    assert samples == ["alpha", "beta"]


def test_refresh_model_samples_success() -> None:
    mysql = FakeSQLExecutor()
    mysql.query_mappings_responses.append([{"model_table_id": 1, "full_name": "main.asset.patients"}])
    mysql.query_mappings_responses.append([{"id": 10, "column_name": "patient_id", "data_type": "STRING", "nullable": 1, "is_active": 1}])

    svc = _SampleService(sql=FakeDatabricksSQLExecutor(), mysql=mysql)
    result = svc.refresh_model_samples(workspace_id="ws-1", schema_name="asset")

    assert result["columns_updated"] == 1
    update_call = next(call for call in mysql.write_calls if "UPDATE model_column" in call.query)
    assert update_call.params["id"] == 10


def test_refresh_model_samples_handles_failures() -> None:
    mysql = FakeSQLExecutor()
    mysql.query_mappings_responses.append([{"model_table_id": 1, "full_name": "main.asset.patients"}])
    mysql.query_mappings_responses.append([{"id": 10, "column_name": "patient_id", "data_type": "STRING", "nullable": 1, "is_active": 1}])

    svc = _FailingSampleService(sql=FakeDatabricksSQLExecutor(), mysql=mysql)
    result = svc.refresh_model_samples(workspace_id="ws-1", schema_name="asset")

    assert result["columns_failed"] == 1
