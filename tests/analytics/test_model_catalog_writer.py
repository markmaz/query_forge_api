# tests/analytics/test_model_catalog_writer.py
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.analytics.model_catalog_writer import ModelCatalogWriter


def _make_mysql():
    """Return a mock ForgeMetaSQL whose transaction() ctx-mgr yields a mock tx."""
    mysql = MagicMock()
    tx = MagicMock()
    mysql.transaction.return_value.__enter__ = MagicMock(return_value=tx)
    mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    return mysql, tx


def test_upsert_tables_calls_execute_write():
    mysql, tx = _make_mysql()
    tx.execute_query_mappings.return_value = [{"id": 1, "name": "orders"}]

    writer = ModelCatalogWriter(mysql=mysql)
    result = writer.upsert_tables(
        tables=[{"table_name": "orders", "comment": "Order data"}],
        origin="databricks",
    )

    assert tx.execute_write.called
    assert result["tables_upserted"] == 1
    assert result["name_to_id"]["orders"] == 1


def test_upsert_tables_preserves_existing_description():
    mysql, tx = _make_mysql()
    tx.execute_query_mappings.return_value = [{"id": 1, "name": "orders"}]

    writer = ModelCatalogWriter(mysql=mysql)
    writer.upsert_tables(
        tables=[{"table_name": "orders", "comment": "source comment"}],
        origin="databricks",
        overwrite_descriptions=False,
    )

    upsert_sql = tx.execute_write.call_args_list[0][0][0]
    # The ON DUPLICATE KEY UPDATE part must not set description = VALUES(description)
    parts = upsert_sql.lower().split("on duplicate key update")
    assert len(parts) == 2
    update_part = parts[1]
    assert "description = values(description)" not in update_part


def test_upsert_tables_overwrites_description_when_requested():
    mysql, tx = _make_mysql()
    tx.execute_query_mappings.return_value = [{"id": 1, "name": "orders"}]

    writer = ModelCatalogWriter(mysql=mysql)
    writer.upsert_tables(
        tables=[{"table_name": "orders", "comment": "source comment"}],
        origin="databricks",
        overwrite_descriptions=True,
    )

    upsert_sql = tx.execute_write.call_args_list[0][0][0]
    parts = upsert_sql.lower().split("on duplicate key update")
    assert "description = values(description)" in parts[1]


def test_mark_tables_missing_issues_update():
    mysql, tx = _make_mysql()
    writer = ModelCatalogWriter(mysql=mysql)
    writer.mark_tables_missing(seen_names={"orders"}, origin="databricks")

    assert tx.execute_write.called
    update_sql = tx.execute_write.call_args[0][0]
    assert "is_missing_in_source" in update_sql.lower()


def test_upsert_columns_sets_is_active():
    mysql, tx = _make_mysql()
    writer = ModelCatalogWriter(mysql=mysql)
    writer.upsert_columns(
        table_id_by_name={"orders": 1},
        columns=[{
            "table_name": "orders", "column_name": "id",
            "data_type": "BIGINT", "ordinal_position": 1,
            "is_nullable": False, "comment": None,
        }],
        origin="databricks",
    )

    assert tx.execute_write.called
    col_sql = tx.execute_write.call_args_list[0][0][0]
    assert "is_active" in col_sql.lower()
    assert "is_missing_in_source" in col_sql.lower()


def test_upsert_columns_skips_unknown_table():
    mysql, tx = _make_mysql()
    writer = ModelCatalogWriter(mysql=mysql)
    writer.upsert_columns(
        table_id_by_name={"known_table": 1},
        columns=[{
            "table_name": "unknown_table", "column_name": "id",
            "data_type": "BIGINT", "ordinal_position": 1,
            "is_nullable": False, "comment": None,
        }],
        origin="databricks",
    )

    # No execute_write if no matching table
    assert not tx.execute_write.called


def test_mark_columns_missing_issues_update():
    mysql, tx = _make_mysql()
    writer = ModelCatalogWriter(mysql=mysql)
    writer.mark_columns_missing(cols_by_table_id={1: {"old_col"}}, origin="databricks")

    assert tx.execute_write.called
    sql = tx.execute_write.call_args[0][0]
    assert "is_missing_in_source" in sql.lower()
