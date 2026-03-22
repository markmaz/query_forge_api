from __future__ import annotations

import pyarrow as pa
import pytest

from app.services.workspace_inventory.workspace_snapshot_service import (
    SnapshotResult,
    WorkspaceSnapshotService,
    _build_uc_metadata_sql,
    _discover_default_catalog_schema,
    _is_qe_from_variant,
    _qf_safe_ident,
    _split_base_and_variant,
)
from tests._support.fakes import FakeDatabricksForgeQueryPort, FakeForgeQueryPort


def test_safe_ident() -> None:
    assert _qf_safe_ident("abc_123") == "abc_123"
    with pytest.raises(ValueError):
        _qf_safe_ident("bad-name")


def test_split_base_and_variant() -> None:
    accepted = {"mx_submitsline", "patient"}
    assert _split_base_and_variant("patient", accepted) == ("patient", None)
    assert _split_base_and_variant("mx_submitsline_150", accepted) == ("mx_submitsline", "150")
    assert _split_base_and_variant("unknown_150", accepted) == ("unknown_150", None)
    assert _split_base_and_variant("", accepted) == ("", None)


def test_build_uc_metadata_sql_guard() -> None:
    sql = _build_uc_metadata_sql("catalog", "schema")
    assert "catalog" in sql
    assert "schema" in sql
    assert "c.table_name     AS qf_table_name" in sql
    assert "c.ordinal_position AS qf_ordinal_position" in sql
    assert "ORDER BY c.table_name, c.ordinal_position" in sql
    with pytest.raises(ValueError):
        _build_uc_metadata_sql("bad-catalog", "schema")


def test_is_qe_from_variant() -> None:
    assert _is_qe_from_variant("QE_1")
    assert not _is_qe_from_variant("150")
    assert not _is_qe_from_variant(None)


def test_discover_default_catalog_schema_empty_rows() -> None:
    sql = FakeDatabricksForgeQueryPort()
    sql.submit_responses.append({"table": pa.table({"catalog": [], "schema": []})})
    with pytest.raises(RuntimeError):
        _discover_default_catalog_schema(sql)


def test_discover_default_catalog_schema() -> None:
    sql = FakeDatabricksForgeQueryPort()
    table = pa.table({"catalog": ["main"], "schema": ["asset"]})
    sql.submit_responses.append({"table": table})
    assert _discover_default_catalog_schema(sql) == ("main", "asset")


def test_sync_snapshot_empty_table() -> None:
    sql = FakeDatabricksForgeQueryPort()
    sql.submit_responses.append(
        {"table": pa.table({"qf_catalog_name": [], "qf_schema_name": [], "qf_table_name": [], "column_name": [], "qf_ordinal_position": [], "data_type": [], "is_nullable": []})}
    )
    mysql = FakeForgeQueryPort()
    svc = WorkspaceSnapshotService(sql=sql, mysql=mysql)

    result = svc.sync_snapshot(workspace_id="ws-1", qf_catalog_name="main", qf_schema_name="asset")

    assert isinstance(result, SnapshotResult)
    assert result.tables_seen == 0
    assert result.columns_seen == 0
    assert mysql.write_calls == []


def test_sync_snapshot_with_rows() -> None:
    sql = FakeDatabricksForgeQueryPort()
    table = pa.Table.from_pylist(
        [
            {
                "qf_catalog_name": "main",
                "qf_schema_name": "asset",
                "qf_table_name": "patient",
                "column_name": "patient_id",
                "qf_ordinal_position": 1,
                "data_type": "STRING",
                "is_nullable": "NO",
            },
            {
                "qf_catalog_name": "main",
                "qf_schema_name": "asset",
                "qf_table_name": "patient",
                "column_name": "gender",
                "qf_ordinal_position": 2,
                "data_type": "STRING",
                "is_nullable": "YES",
            },
            {
                "qf_catalog_name": "main",
                "qf_schema_name": "asset",
                "qf_table_name": "diagnosis_150",
                "column_name": "code",
                "qf_ordinal_position": 1,
                "data_type": "STRING",
                "is_nullable": "YES",
            },
        ]
    )
    sql.submit_responses.append({"table": table})

    mysql = FakeForgeQueryPort()
    # _load_current_workspace_table_ids is the only execute_query_mappings call;
    # it expects rows keyed by full_name.
    mysql.query_mappings_responses.append(
        [
            {"id": 101, "full_name": "main.asset.patient"},
            {"id": 202, "full_name": "main.asset.diagnosis_150"},
        ]
    )

    svc = WorkspaceSnapshotService(sql=sql, mysql=mysql)
    result = svc.sync_snapshot(workspace_id="ws-1", qf_catalog_name="main", qf_schema_name="asset")

    assert result.tables_seen == 2
    assert result.columns_seen == 3

    table_insert = next(
        call for call in mysql.write_calls if "INSERT INTO workspace_table" in call.query
    )
    assert len(table_insert.params) == 2

    column_insert = next(
        call for call in mysql.write_calls if "INSERT INTO workspace_column" in call.query
    )
    assert len(column_insert.params) == 3
