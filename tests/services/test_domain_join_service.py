from __future__ import annotations

import datetime

import pytest

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeExecResult
from app.services.domain.domain_join_service import DomainJoinService
from tests._support.fakes import FakeForgeQueryPort


def _basic_join_spec(qf_from_id: int = 1, qf_to_id: int = 2) -> dict:
    return {
        "on": [
            {
                "left": {"columnName": "left_col", "workspaceTableId": qf_from_id},
                "right": {"columnName": "right_col", "workspaceTableId": qf_to_id},
            }
        ]
    }


def _expr_join_spec(qf_from_id: int = 1, qf_to_id: int = 2) -> dict:
    return {
        "on": [
            {
                "left": {
                    "expr": "get_json_object({from}.json_col, '$.key')",
                    "workspaceTableId": qf_from_id,
                },
                "right": {"columnName": "right_col", "workspaceTableId": qf_to_id},
            }
        ]
    }


class _NoLastRowId:
    pass


class _EmptyKeyService(DomainJoinService):
    def _parse_json_expr(self, expr: str) -> tuple[str, str, str]:
        return "from", "json_col", ""


def test_list_domain_joins_formats_rows():
    sql = FakeForgeQueryPort()
    created = datetime.datetime(2024, 1, 1, 2, 3, 4)
    sql.query_mappings_responses = [[{"id": 1, "created_at": created}]]
    svc = DomainJoinService(sql=sql)

    rows = svc.list_domain_joins(workspace_id="ws", domain_id=1)

    assert rows[0]["created_at"] == created.isoformat()
    assert "FROM domain_table_join" in sql.query_mappings_calls[0].query


def test_create_join_inserts():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"workspace_table_id": 1}, {"workspace_table_id": 2}],
        [],
        [],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=7)]
    svc = DomainJoinService(sql=sql)

    out = svc.create_join(
        workspace_id="ws",
        domain_id=1,
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec=_basic_join_spec(),
        sort_order=0,
    )

    assert out["ok"] is True
    assert out["id"] == "7"


def test_create_join_existing_updates():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"workspace_table_id": 1}, {"workspace_table_id": 2}],
        [],
        [{"id": "j1", "is_active": 0}],
    ]
    svc = DomainJoinService(sql=sql)

    out = svc.create_join(
        workspace_id="ws",
        domain_id=1,
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec=_basic_join_spec(),
        sort_order=0,
    )

    assert out["id"] == "j1"
    assert sql.write_calls


def test_create_join_insert_no_lastrowid():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"workspace_table_id": 1}, {"workspace_table_id": 2}],
        [],
        [],
    ]
    sql.insert_responses = [_NoLastRowId()]
    svc = DomainJoinService(sql=sql)

    out = svc.create_join(
        workspace_id="ws",
        domain_id=1,
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec=_basic_join_spec(),
        sort_order=0,
    )

    assert out["id"] is None


def test_create_join_with_expr_validates_expr_columns():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"workspace_table_id": 1}, {"workspace_table_id": 2}],
        [{"1": 1}],
        [],
        [],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=11)]
    svc = DomainJoinService(sql=sql)

    out = svc.create_join(
        workspace_id="ws",
        domain_id=1,
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec=_expr_join_spec(),
        sort_order=0,
    )

    assert out["id"] == "11"


def test_update_join_success():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"id": "j1"}],
        [{"workspace_table_id": 1}, {"workspace_table_id": 2}],
        [{"id": "j1"}],
    ]
    svc = DomainJoinService(sql=sql)

    out = svc.update_join(
        workspace_id="ws",
        domain_id=1,
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec=_basic_join_spec(),
        sort_order=1,
    )

    assert out["ok"] is True
    assert sql.write_calls


def test_update_join_not_found():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [],
    ]
    svc = DomainJoinService(sql=sql)

    with pytest.raises(ForgeError):
        svc.update_join(
            workspace_id="ws",
            domain_id=1,
            join_id="missing",
            from_workspace_table_id=1,
            to_workspace_table_id=2,
            join_type="LEFT",
            join_spec=_basic_join_spec(),
            sort_order=1,
        )


def test_delete_join_success():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"id": "j1"}],
    ]
    svc = DomainJoinService(sql=sql)

    out = svc.delete_join(workspace_id="ws", domain_id=1, join_id="j1")

    assert out["ok"] is True
    assert sql.write_calls


def test_set_primary_table_success():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"1": 1}],
        [
            {
                "workspace_table_id": 1,
                "model_table_id": None,
                "model_table_name": None,
                "relation_kind": "",
                "is_primary": 1,
                "sort_order": 0,
                "table_alias": None,
                "role": None,
                "catalog_name": "c",
                "schema_name": "s",
                "table_name": "t",
                "full_name": "c.s.t",
                "qf_variant_code": None,
                "is_qe": 0,
                "qf_exists_in_dbx": 0,
                "qf_last_seen_at": None,
            }
        ],
    ]
    svc = DomainJoinService(sql=sql)

    out = svc.set_primary_table(workspace_id="ws", domain_id=1, workspace_table_id=1)

    assert out[0]["workspace_table_id"] == 1
    assert len(sql.write_calls) == 3


def test_set_primary_table_missing_table():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [],
    ]
    svc = DomainJoinService(sql=sql)

    with pytest.raises(ForgeError):
        svc.set_primary_table(workspace_id="ws", domain_id=1, workspace_table_id=2)


def test_validate_join_type_invalid():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc._validate_join_type("BAD")


def test_validate_join_spec_invalid_shapes():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc._validate_join_spec("bad")
    with pytest.raises(ForgeError):
        svc._validate_join_spec({"on": []})
    with pytest.raises(ForgeError):
        svc._validate_join_spec({"on": ["bad"]})
    with pytest.raises(ForgeError):
        svc._validate_join_spec({"on": [{"left": "bad", "right": {"columnName": "b"}}]})
    with pytest.raises(ForgeError):
        svc._validate_join_spec(
            {"on": [{"op": "!=", "left": {"columnName": "a"}, "right": {"columnName": "b"}}]}
        )


def test_validate_join_side_errors():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc._validate_join_spec(
            {"on": [{"left": {"expr": "x", "columnName": "a"}, "right": {"columnName": "b"}}]}
        )
    with pytest.raises(ForgeError):
        svc._validate_join_spec({"on": [{"left": {}, "right": {"columnName": "b"}}]})
    with pytest.raises(ForgeError):
        svc._validate_join_spec(
            {"on": [{"left": {"expr": 123}, "right": {"columnName": "b"}}]}
        )
    with pytest.raises(ForgeError):
        svc._validate_join_spec(
            {"on": [{"left": {"columnName": 123}, "right": {"columnName": "b"}}]}
        )
    with pytest.raises(ForgeError):
        svc._validate_join_spec({"on": [{"left": {"columnName": "a"}, "right": {}}]})


def test_validate_join_tables_mismatch():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    spec_left = {"on": [{"left": {"columnName": "a", "workspaceTableId": 9}, "right": {"columnName": "b"}}]}
    with pytest.raises(ForgeError):
        svc._validate_join_tables(spec_left, qf_from_id=1, qf_to_id=2)
    spec_right = {
        "on": [
            {"left": {"columnName": "a"}, "right": {"columnName": "b", "workspaceTableId": 9}}
        ]
    }
    with pytest.raises(ForgeError):
        svc._validate_join_tables(spec_right, qf_from_id=1, qf_to_id=2)


def test_validate_expr_side_errors():
    sql = FakeForgeQueryPort()
    svc = DomainJoinService(sql=sql)
    with pytest.raises(ForgeError):
        svc._validate_expr_side(
            sql,
            {"expr": "get_json_object({to}.col, '$.key')"},
            expected_scope="from",
            workspace_table_id=1,
            qf_side_label="left",
        )

    sql.query_mappings_responses = [[]]
    with pytest.raises(ForgeError):
        svc._validate_expr_side(
            sql,
            {"expr": "get_json_object({from}.col, '$.key')"},
            expected_scope="from",
            workspace_table_id=1,
            qf_side_label="left",
        )

    empty_key_sql = FakeForgeQueryPort()
    empty_key_sql.query_mappings_responses = [[{"1": 1}]]
    empty_key_svc = _EmptyKeyService(sql=empty_key_sql)
    with pytest.raises(ForgeError):
        empty_key_svc._validate_expr_side(
            empty_key_svc._sql,
            {"expr": "get_json_object({from}.col, '$.key')"},
            expected_scope="from",
            workspace_table_id=1,
            qf_side_label="left",
        )


def test_parse_json_expr_invalid():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc._parse_json_expr("bad")


def test_column_exists_true_false():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"1": 1}], []]
    svc = DomainJoinService(sql=sql)

    assert svc._column_exists(sql, 1, "col") is True
    assert svc._column_exists(sql, 1, "col") is False


def test_validate_join_tables_same_id():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc.create_join(
            workspace_id="ws",
            domain_id=1,
            from_workspace_table_id=1,
            to_workspace_table_id=1,
            join_type="LEFT",
            join_spec=_basic_join_spec(),
            sort_order=0,
        )


def test_update_join_same_table_ids():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc.update_join(
            workspace_id="ws",
            domain_id=1,
            join_id="j1",
            from_workspace_table_id=1,
            to_workspace_table_id=1,
            join_type="LEFT",
            join_spec=_basic_join_spec(),
            sort_order=0,
        )


def test_validate_join_spec_right_expr_and_col():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc._validate_join_spec(
            {
                "on": [
                    {
                        "left": {"columnName": "a"},
                        "right": {"expr": "x", "columnName": "b"},
                    }
                ]
            }
        )


def test_validate_join_spec_right_expr_type():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc._validate_join_spec(
            {
                "on": [
                    {
                        "left": {"columnName": "a"},
                        "right": {"expr": 1},
                    }
                ]
            }
        )


def test_validate_join_spec_right_col_type():
    svc = DomainJoinService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc._validate_join_spec(
            {
                "on": [
                    {
                        "left": {"columnName": "a"},
                        "right": {"columnName": 1},
                    }
                ]
            }
        )


def test_validate_join_unique_to_table_conflict():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"id": 1}]]
    svc = DomainJoinService(sql=sql)
    with pytest.raises(ForgeError):
        svc._ensure_unique_to_table(sql, 1, 2, exclude_id=None)


def test_validate_join_expr_columns_missing_scope_column():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    svc = DomainJoinService(sql=sql)
    join_spec = {
        "on": [
            {
                "left": {"expr": "get_json_object({from}.json_col, '$.key')"},
                "right": {"columnName": "r"},
            }
        ]
    }
    with pytest.raises(ForgeError):
        svc._validate_join_expr_columns(sql, join_spec, qf_from_id=1, qf_to_id=2)


def test_validate_join_tables_domain_missing():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"workspace_table_id": 1}],
    ]
    svc = DomainJoinService(sql=sql)
    with pytest.raises(ForgeError):
        svc.create_join(
            workspace_id="ws",
            domain_id=1,
            from_workspace_table_id=1,
            to_workspace_table_id=2,
            join_type="LEFT",
            join_spec=_basic_join_spec(),
            sort_order=0,
        )


def test_ensure_domain_not_found():
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    svc = DomainJoinService(sql=sql)
    with pytest.raises(ForgeError):
        svc._ensure_domain(sql, "ws", 1)
