from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.admin.domain_table_command_service import DomainTableCommandService
from tests._support.fakes import FakeForgeQueryPort


def test_add_or_update_table_sets_primary_and_returns_row() -> None:
    sql = FakeForgeQueryPort()
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
                "qf_variant_code": None,
                "is_qe": 0,
                "qf_exists_in_dbx": 1,
                "qf_last_seen_at": None,
            }
        ],
    ]

    service = DomainTableCommandService(sql=sql)
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


def test_normalize_ids_surfaces_unexpected_int_errors() -> None:
    class _BadInt:
        def __int__(self) -> int:
            raise AssertionError("unexpected id parse bug")

    with pytest.raises(AssertionError, match="unexpected id parse bug"):
        DomainTableCommandService._normalize_ids([_BadInt()], "add")


def test_normalize_ids_wraps_expected_int_errors() -> None:
    with pytest.raises(ForgeError, match="'add' must contain integers"):
        DomainTableCommandService._normalize_ids(["abc"], "add")
