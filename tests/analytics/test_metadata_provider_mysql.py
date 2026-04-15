# tests/analytics/test_metadata_provider_mysql.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.adapters.analytics.mysql_metadata_provider import MySQLMetadataProvider
from app.ports.sql_executor_abc import SQLExecutor


def _make_executor(rows=None):
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.return_value = rows or []
    ex.get_dialect.return_value = "mysql"
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
    provider = MySQLMetadataProvider(executor=ex)
    result = provider.list_tables(catalog=None, schema="mydb")
    assert result[0]["table_name"] == "orders"


def test_list_tables_queries_information_schema():
    ex = _make_executor()
    provider = MySQLMetadataProvider(executor=ex)
    provider.list_tables(catalog=None, schema="mydb")
    sql = ex.execute.call_args[0][0]
    assert "information_schema" in sql.lower()


def test_list_columns_normalizes_nullable():
    ex = _make_executor([
        {"table_name": "t", "column_name": "c", "data_type": "varchar",
         "ordinal_position": 1, "is_nullable": "NO", "comment": ""}
    ])
    provider = MySQLMetadataProvider(executor=ex)
    result = provider.list_columns(catalog=None, schema="mydb")
    assert result[0]["is_nullable"] is False


def test_list_columns_filters_by_table_names():
    ex = _make_executor()
    provider = MySQLMetadataProvider(executor=ex)
    provider.list_columns(catalog=None, schema="mydb", table_names=["orders"])
    sql = ex.execute.call_args[0][0]
    assert "orders" in sql


def test_profile_uses_limit_sampling():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = [
        [{"row_count": 300}],
        [{"null_id": 0, "dist_id": 300}],
    ]
    ex.get_dialect.return_value = "mysql"
    provider = MySQLMetadataProvider(executor=ex)

    result = provider.profile_table_columns(
        table_ref="`mydb`.`orders`",
        columns=[{"column_name": "id", "data_type": "int", "is_nullable": False}],
        options=_DEFAULT_OPTIONS,
    )

    count_sql = ex.execute.call_args_list[0][0][0]
    assert "LIMIT" in count_sql.upper()
    assert "id" in result
    assert result["id"]["null_count"] == 0


def test_profile_error_captured():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = RuntimeError("mysql boom")
    ex.get_dialect.return_value = "mysql"
    provider = MySQLMetadataProvider(executor=ex)

    result = provider.profile_table_columns(
        table_ref="`mydb`.`orders`",
        columns=[{"column_name": "id", "data_type": "int", "is_nullable": False}],
        options=_DEFAULT_OPTIONS,
    )
    assert result["id"]["sample_error"] is not None


def test_profile_falls_back_to_sample_values_for_high_cardinality_columns():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = [
        [{"row_count": 300}],
        [{"null_name": 0, "dist_name": 3000}],
        [{"val": "alpha"}, {"val": "beta"}],
    ]
    ex.get_dialect.return_value = "mysql"
    provider = MySQLMetadataProvider(executor=ex)

    result = provider.profile_table_columns(
        table_ref="`mydb`.`people`",
        columns=[{"column_name": "name", "data_type": "varchar", "is_nullable": True}],
        options={**_DEFAULT_OPTIONS, "skip_top_values_for_id_like_cols": False},
    )

    sample_sql = ex.execute.call_args_list[2][0][0]
    assert "SELECT DISTINCT" in sample_sql.upper()
    assert "GROUP BY" not in sample_sql.upper()
    assert result["name"]["top_values"] == ["alpha", "beta"]


def test_profile_surfaces_unexpected_top_value_sampling_errors():
    ex = MagicMock(spec=SQLExecutor)
    ex.execute.side_effect = [
        [{"row_count": 300}],
        [{"null_name": 0, "dist_name": 3}],
        AssertionError("unexpected mysql top value bug"),
    ]
    ex.get_dialect.return_value = "mysql"
    provider = MySQLMetadataProvider(executor=ex)

    with pytest.raises(AssertionError, match="unexpected mysql top value bug"):
        provider.profile_table_columns(
            table_ref="`mydb`.`people`",
            columns=[{"column_name": "name", "data_type": "varchar", "is_nullable": True}],
            options={**_DEFAULT_OPTIONS, "skip_top_values_for_id_like_cols": False},
        )


def test_list_schemas():
    ex = _make_executor([
        {"schema_name": "app_db"},
        {"schema_name": "reporting"},
    ])
    provider = MySQLMetadataProvider(executor=ex)
    result = provider.list_schemas(catalog=None)
    assert result == ["app_db", "reporting"]
    sql = ex.execute.call_args[0][0]
    assert "information_schema.schemata" in sql


def test_list_schemas_ignores_catalog():
    """MySQL has no catalog concept — catalog param must be silently ignored."""
    ex = _make_executor([{"schema_name": "app_db"}])
    provider = MySQLMetadataProvider(executor=ex)
    result = provider.list_schemas(catalog="ignored_value")
    assert result == ["app_db"]
    sql = ex.execute.call_args[0][0]
    assert "ignored_value" not in sql
