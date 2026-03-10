from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.exceptions.forge_error import ForgeError
from app.services.domain.domain_table_read_service import DomainTableReadService
from tests._support.fakes import FakeForgeQueryPort


def test_list_domain_tables() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "workspace_table_id": 1,
                "model_table_id": None,
                "model_table_name": None,
                "relation_kind": "JOIN",
                "is_primary": 1,
                "sort_order": 0,
                "table_alias": None,
                "role": None,
                "filter_mode": "AUTO",
                "cardinality": "ONE",
                "catalog_name": "main",
                "schema_name": "asset",
                "table_name": "tbl",
                "full_name": "main.asset.tbl",
                "qf_variant_code": None,
                "is_qe": 0,
                "qf_exists_in_dbx": 1,
                "qf_last_seen_at": None,
            }
        ]
    ]
    service = DomainTableReadService(sql=sql, metadata_mode="legacy")
    rows = service.list_domain_tables(workspace_id="ws1", domain_id=1)
    assert rows[0]["workspace_table_id"] == 1


def test_get_domain_validation() -> None:
    service = DomainTableReadService(sql=FakeForgeQueryPort(), metadata_mode="legacy")
    with pytest.raises(ForgeError):
        service.get_domain(workspace_id="", domain_name="Name")


def test_list_workspace_tables_calls_registry_sync_when_schema_present(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    service = DomainTableReadService(sql=sql, metadata_mode="legacy")
    called = {}

    def fake_sync(*_args, **_kwargs):
        called["ok"] = True

    monkeypatch.setattr(
        service,
        "_sync_workspace_inventory_from_registry",
        fake_sync,
    )
    service.list_workspace_tables(workspace_id="ws1", schema_name="asset", ensure_snapshot=True)
    assert called["ok"] is True


def test_list_workspace_tables_skips_registry_sync_when_schema_missing(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    service = DomainTableReadService(sql=sql, metadata_mode="legacy")
    called = {"count": 0}

    def fake_sync(*_args, **_kwargs):
        called["count"] += 1

    monkeypatch.setattr(
        service,
        "_sync_workspace_inventory_from_registry",
        fake_sync,
    )
    service.list_workspace_tables(workspace_id="ws1", ensure_snapshot=True)
    assert called["count"] == 0


def test_sync_workspace_inventory_uses_factory_registry(monkeypatch) -> None:
    app = Flask(__name__)
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [],
        [{"id": 11, "table_name": "orders"}],
    ]
    service = DomainTableReadService(sql=sql, metadata_mode="legacy")

    executor = MagicMock()
    executor.get_dialect.return_value = "snowflake"
    registry = MagicMock()
    registry.get.return_value = executor

    provider = MagicMock()
    provider.list_tables.return_value = [{"table_name": "orders"}]
    provider.list_columns.return_value = [
        {
            "table_name": "orders",
            "column_name": "id",
            "data_type": "NUMBER",
            "is_nullable": False,
            "ordinal_position": 1,
        }
    ]

    captured = {}

    def fake_create(dialect, exec_obj):
        captured["dialect"] = dialect
        captured["executor"] = exec_obj
        return provider

    monkeypatch.setattr(
        "app.services.domain.domain_table_read_service.MetadataProviderFactory.create",
        fake_create,
    )

    with app.app_context():
        app.extensions["analytics_registry"] = registry
        service._sync_workspace_inventory_from_registry(
            workspace_id="ws1",
            schema_name="MEDICAL_SALES",
            catalog_name="QUERYFORGE_DEMO",
        )

    registry.get.assert_called_once_with("primary")
    assert captured["dialect"] == "snowflake"
    assert captured["executor"] is executor
    provider.list_tables.assert_called_once_with("QUERYFORGE_DEMO", "MEDICAL_SALES")
    provider.list_columns.assert_called_once_with("QUERYFORGE_DEMO", "MEDICAL_SALES", ["orders"])
    assert any("INSERT INTO workspace_table" in call.query for call in sql.write_calls)
    assert any("INSERT INTO workspace_column" in call.query for call in sql.write_calls)
