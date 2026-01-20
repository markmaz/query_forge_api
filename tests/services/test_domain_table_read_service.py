from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain.domain_table_read_service import DomainTableReadService
from tests._support.fakes import FakeSQLExecutor


def test_list_domain_tables() -> None:
    sql = FakeSQLExecutor()
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
                "variant_code": None,
                "is_qe": 0,
                "exists_in_dbx": 1,
                "last_seen_at": None,
            }
        ]
    ]
    service = DomainTableReadService(sql=sql)
    rows = service.list_domain_tables(workspace_id="ws1", domain_id=1)
    assert rows[0]["workspace_table_id"] == 1


def test_get_domain_validation() -> None:
    service = DomainTableReadService(sql=FakeSQLExecutor())
    with pytest.raises(ServiceError):
        service.get_domain(workspace_id="", domain_name="Name")


def test_list_workspace_tables_calls_snapshot(monkeypatch) -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [[]]
    service = DomainTableReadService(sql=sql)
    called = {}

    def fake_ensure(*_args, **_kwargs):
        called["ok"] = True

    monkeypatch.setattr(
        "app.services.domain.domain_table_read_service.WorkspaceSnapshotEnsureService.ensure",
        fake_ensure,
    )
    service.list_workspace_tables(workspace_id="ws1", ensure_snapshot=True)
    assert called["ok"] is True
