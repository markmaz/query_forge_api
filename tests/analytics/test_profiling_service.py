# tests/analytics/test_profiling_service.py
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.analytics.profiling_service import ProfilingService


def _make_mysql():
    mysql = MagicMock()
    tx = MagicMock()
    mysql.transaction.return_value.__enter__ = MagicMock(return_value=tx)
    mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    return mysql, tx


def _make_provider_with_stats(col_stats):
    provider = MagicMock()
    provider.profile_table_columns.return_value = col_stats
    return provider


def test_profile_and_persist_calls_provider_per_table():
    provider = _make_provider_with_stats({
        "id": {"null_count": 0, "null_pct": 0.0, "approx_distinct": 100,
               "top_values": [], "sample_row_count": 100, "sample_error": None}
    })
    mysql, tx = _make_mysql()
    svc = ProfilingService(mysql=mysql)

    svc.profile_and_persist(
        provider=provider,
        catalog="main",
        schema="sales",
        table_id_by_name={"orders": 1},
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False}],
        options={},
    )

    assert provider.profile_table_columns.called
    # table_ref should include catalog, schema, table_name
    call_kwargs = provider.profile_table_columns.call_args
    table_ref = call_kwargs[1]["table_ref"] if call_kwargs[1] else call_kwargs[0][0]
    assert "orders" in table_ref


def test_profile_table_failure_does_not_abort_run():
    provider = MagicMock()
    provider.profile_table_columns.side_effect = RuntimeError("table boom")
    mysql, tx = _make_mysql()
    svc = ProfilingService(mysql=mysql)

    # Should not raise even though both tables fail
    result = svc.profile_and_persist(
        provider=provider,
        catalog=None,
        schema="sales",
        table_id_by_name={"orders": 1, "items": 2},
        columns=[
            {"table_name": "orders", "column_name": "id", "data_type": "BIGINT", "is_nullable": False},
            {"table_name": "items",  "column_name": "sku", "data_type": "VARCHAR", "is_nullable": True},
        ],
        options={},
    )

    assert result["tables_failed"] == 2
    assert result["profiled"] == 0


def test_profile_persists_sample_stats_to_mysql():
    provider = _make_provider_with_stats({
        "id": {
            "null_count": 5, "null_pct": 0.05, "approx_distinct": 95,
            "top_values": ["a"],
            "sample_row_count": 100, "sample_error": None,
        }
    })
    mysql, tx = _make_mysql()
    svc = ProfilingService(mysql=mysql)

    svc.profile_and_persist(
        provider=provider,
        catalog=None,
        schema="sales",
        table_id_by_name={"orders": 1},
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False}],
        options={},
    )

    assert tx.execute_write.called
    update_sql = tx.execute_write.call_args_list[-1][0][0]
    assert "sample_values_json" in update_sql.lower()
    assert "sample_stats_json" in update_sql.lower()
    assert "sample_ran_at" in update_sql.lower()


def test_profile_skips_table_not_in_table_id_map():
    provider = MagicMock()
    mysql, tx = _make_mysql()
    svc = ProfilingService(mysql=mysql)

    result = svc.profile_and_persist(
        provider=provider,
        catalog=None,
        schema="sales",
        table_id_by_name={},  # empty — no known tables
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False}],
        options={},
    )

    # Provider should not be called since no tables are in the map
    assert not provider.profile_table_columns.called
    assert result["profiled"] == 0
    assert result["tables_failed"] == 0
