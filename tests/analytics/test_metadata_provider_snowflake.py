# tests/analytics/test_metadata_provider_snowflake.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.adapters.analytics.snowflake_metadata_provider import SnowflakeMetadataProvider
from app.ports.sql_executor_abc import SQLExecutor


@pytest.fixture
def executor():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.return_value = []
    ex.get_dialect.return_value = "snowflake"
    return ex


def _make_executor(rows=None):
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.return_value = rows or []
    ex.get_dialect.return_value = "snowflake"
    return ex


_DEFAULT_OPTIONS = {
    "sample_percent": 0.10,
    "sample_row_cap": 200_000,
    "per_column_limit": 10,
    "max_distinct_for_top_values": 250,
    "profile_top_values_only_for_string_types": True,
    "skip_top_values_for_id_like_cols": True,
}


def test_list_tables_returns_tables():
    ex = _make_executor([{"table_name": "orders", "table_type": "BASE TABLE", "comment": None}])
    provider = SnowflakeMetadataProvider(executor=ex)
    result = provider.list_tables(catalog="mydb", schema="sales")
    assert len(result) == 1
    assert result[0]["table_name"] == "orders"


def test_list_tables_handles_uppercase_keys():
    ex = _make_executor([{"TABLE_NAME": "ORDERS", "TABLE_TYPE": "BASE TABLE", "COMMENT": None}])
    provider = SnowflakeMetadataProvider(executor=ex)
    result = provider.list_tables(catalog="mydb", schema="sales")
    assert len(result) == 1
    assert result[0]["table_name"] == "ORDERS"


def test_list_tables_queries_information_schema():
    ex = _make_executor()
    provider = SnowflakeMetadataProvider(executor=ex)
    provider.list_tables(catalog="mydb", schema="sales")
    sql = ex.execute.call_args[0][0]
    assert "information_schema" in sql.lower()


def test_list_columns_returns_columns():
    ex = _make_executor([
        {"table_name": "orders", "column_name": "id", "data_type": "NUMBER",
         "ordinal_position": 1, "is_nullable": "NO", "comment": None}
    ])
    provider = SnowflakeMetadataProvider(executor=ex)
    result = provider.list_columns(catalog="mydb", schema="sales")
    assert result[0]["is_nullable"] is False


def test_list_columns_handles_uppercase_keys():
    ex = _make_executor([
        {
            "TABLE_NAME": "ORDERS",
            "COLUMN_NAME": "ID",
            "DATA_TYPE": "NUMBER",
            "ORDINAL_POSITION": 1,
            "IS_NULLABLE": "NO",
            "COMMENT": None,
        }
    ])
    provider = SnowflakeMetadataProvider(executor=ex)
    result = provider.list_columns(catalog="mydb", schema="sales")
    assert result[0]["table_name"] == "ORDERS"
    assert result[0]["column_name"] == "ID"
    assert result[0]["is_nullable"] is False


def test_list_columns_filters_by_table_names():
    ex = _make_executor()
    provider = SnowflakeMetadataProvider(executor=ex)
    provider.list_columns(catalog="mydb", schema="sales", table_names=["orders"])
    sql = ex.execute.call_args[0][0]
    assert "orders" in sql


def test_profile_uses_sample_clause():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = [
        [{"ROW_COUNT": 500}],
        [{"NULL_ID": 0, "DIST_ID": 500}],
    ]
    ex.get_dialect.return_value = "snowflake"
    provider = SnowflakeMetadataProvider(executor=ex)

    result = provider.profile_table_columns(
        table_ref="mydb.sales.orders",
        columns=[{"column_name": "id", "data_type": "NUMBER", "is_nullable": False}],
        options=_DEFAULT_OPTIONS,
    )

    count_sql = ex.execute.call_args_list[0][0][0]
    assert "SAMPLE" in count_sql.upper() or "TABLESAMPLE" in count_sql.upper()
    assert "id" in result
    assert result["id"]["null_count"] == 0


def test_profile_top_values_handles_uppercase_alias_keys():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = [
        [{"ROW_COUNT": 10}],
        [{"NULL_NAME": 0, "DIST_NAME": 2}],
        [{"VAL": "A", "CNT": 7}],
    ]
    ex.get_dialect.return_value = "snowflake"
    provider = SnowflakeMetadataProvider(executor=ex)
    options = dict(_DEFAULT_OPTIONS)
    options["skip_top_values_for_id_like_cols"] = False

    result = provider.profile_table_columns(
        table_ref="mydb.sales.people",
        columns=[{"column_name": "name", "data_type": "VARCHAR", "is_nullable": True}],
        options=options,
    )

    assert result["name"]["top_values"] == ["A"]


def test_profile_falls_back_to_sample_values_for_high_cardinality_columns():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = [
        [{"ROW_COUNT": 10}],
        [{"NULL_NAME": 0, "DIST_NAME": 5000}],
        [{"VAL": "A"}, {"VAL": "B"}],
    ]
    ex.get_dialect.return_value = "snowflake"
    provider = SnowflakeMetadataProvider(executor=ex)

    result = provider.profile_table_columns(
        table_ref="mydb.sales.people",
        columns=[{"column_name": "name", "data_type": "VARCHAR", "is_nullable": True}],
        options={**_DEFAULT_OPTIONS, "skip_top_values_for_id_like_cols": False},
    )

    sample_sql = ex.execute.call_args_list[2][0][0]
    assert "SELECT DISTINCT" in sample_sql.upper()
    assert "GROUP BY" not in sample_sql.upper()
    assert result["name"]["top_values"] == ["A", "B"]


def test_profile_surfaces_unexpected_top_value_sampling_errors():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = [
        [{"ROW_COUNT": 10}],
        [{"NULL_NAME": 0, "DIST_NAME": 3}],
        AssertionError("unexpected snowflake top value bug"),
    ]
    ex.get_dialect.return_value = "snowflake"
    provider = SnowflakeMetadataProvider(executor=ex)

    with pytest.raises(AssertionError, match="unexpected snowflake top value bug"):
        provider.profile_table_columns(
            table_ref="mydb.sales.people",
            columns=[{"column_name": "name", "data_type": "VARCHAR", "is_nullable": True}],
            options={**_DEFAULT_OPTIONS, "skip_top_values_for_id_like_cols": False},
        )


def test_profile_error_captured_per_column():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = RuntimeError("snowflake boom")
    ex.get_dialect.return_value = "snowflake"
    provider = SnowflakeMetadataProvider(executor=ex)

    result = provider.profile_table_columns(
        table_ref="mydb.sales.orders",
        columns=[{"column_name": "id", "data_type": "NUMBER", "is_nullable": False}],
        options=_DEFAULT_OPTIONS,
    )

    assert result["id"]["sample_error"] is not None


def test_list_schemas_without_catalog(executor):
    executor.execute.return_value = [
        {"SCHEMA_NAME": "SALES"},
        {"SCHEMA_NAME": "FINANCE"},
    ]
    provider = SnowflakeMetadataProvider(executor=executor)
    result = provider.list_schemas(catalog=None)
    assert result == ["FINANCE", "SALES"]  # sorted
    sql = executor.execute.call_args[0][0]
    assert "information_schema.schemata" in sql


def test_list_schemas_with_catalog(executor):
    executor.execute.return_value = [
        {"SCHEMA_NAME": "PUBLIC"},
    ]
    provider = SnowflakeMetadataProvider(executor=executor)
    result = provider.list_schemas(catalog="MY_DB")
    assert result == ["PUBLIC"]
    sql = executor.execute.call_args[0][0]
    assert '"MY_DB"' in sql


def test_list_schemas_rejects_unsafe_catalog(executor):
    provider = SnowflakeMetadataProvider(executor=executor)
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        provider.list_schemas(catalog="bad;drop")
