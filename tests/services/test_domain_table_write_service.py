from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain.domain_table_write_service import DomainTableWriteService
from tests._support.fakes import FakeSQLExecutor


def test_normalize_ids_validates() -> None:
    assert DomainTableWriteService._normalize_ids([1, 2, 2], "add") == [1, 2]

    with pytest.raises(ServiceError, match="must be a list"):
        DomainTableWriteService._normalize_ids("bad", "add")

    with pytest.raises(ServiceError, match="must contain integers"):
        DomainTableWriteService._normalize_ids([1, "x"], "add")

    with pytest.raises(ServiceError, match="must contain positive"):
        DomainTableWriteService._normalize_ids([0], "add")


def test_add_or_update_table_sets_primary_and_returns_row() -> None:
    sql = FakeSQLExecutor()
    sql.query_responses = [[("ok",)], []]
    sql.query_mappings_responses = [
        [{"ok_domain": 1, "ok_table": 1}],
        [
            {
                "workspace_table_id": 10,
                "model_table_id": None,
                "model_table_name": None,
                "relation_kind": "JOIN",
                "is_primary": 1,
                "sort_order": 0,
                "table_alias": "pt",
                "role": None,
                "catalog_name": "main",
                "schema_name": "asset",
                "table_name": "patients",
                "full_name": "main.asset.patients",
                "variant_code": None,
                "is_qe": 0,
                "exists_in_dbx": 1,
                "last_seen_at": None,
            }
        ],
    ]

    service = DomainTableWriteService(sql=sql)
    res = service.add_or_update_table(
        workspace_id="ws1",
        user_id="user1",
        domain_id=1,
        workspace_table_id=10,
        relation_kind="join",
        relation_kind_set=True,
        role="primary",
        role_set=True,
        sort_order=1,
        sort_order_set=True,
        table_alias="pt",
        table_alias_set=True,
        filter_mode="where",
        filter_mode_set=True,
        cardinality="one",
        cardinality_set=True,
        set_primary_if_empty=True,
    )
    assert res["workspace_table_id"] == 10
    assert sql.write_calls


def test_apply_changes_add_remove() -> None:
    sql = FakeSQLExecutor()
    sql.query_responses = [[("ok",)], [("ok",)]]
    sql.query_mappings_responses = [[{"id": 1}, {"id": 2}, {"id": 3}]]
    sql.write_responses = [1, 0, 0]

    service = DomainTableWriteService(sql=sql)
    res = service.apply_changes(
        workspace_id="ws1",
        user_id="user1",
        domain_id=1,
        add=[1, 2],
        remove=[3],
    )
    assert res == {"ok": True, "added": 2, "removed": 1}


def test_apply_changes_missing_domain() -> None:
    sql = FakeSQLExecutor()
    sql.query_responses = [[("ok",)], []]
    service = DomainTableWriteService(sql=sql)
    with pytest.raises(ServiceError, match="Domain not found"):
        service.apply_changes(
            workspace_id="ws1",
            user_id="user1",
            domain_id=1,
            add=[1],
            remove=None,
        )
