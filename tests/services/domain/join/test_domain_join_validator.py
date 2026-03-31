from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.join.domain_join_expression_parser import DomainJoinExpressionParser
from app.services.domain.join.domain_join_validator import DomainJoinValidator
from tests._support.fakes import FakeForgeQueryPort


def _validator() -> DomainJoinValidator:
    return DomainJoinValidator(expression_parser=DomainJoinExpressionParser())


def test_prepare_payload_normalizes_ids() -> None:
    payload = _validator().prepare_payload(
        domain_id=1,
        from_workspace_table_id="1",
        to_workspace_table_id="2",
        join_type="LEFT",
        join_spec={
            "on": [
                {
                    "left": {"columnName": "left_col", "workspaceTableId": 1},
                    "right": {"columnName": "right_col", "workspaceTableId": 2},
                }
            ]
        },
        sort_order="3",
    )
    assert payload.from_workspace_table_id == 1
    assert payload.to_workspace_table_id == 2
    assert payload.sort_order == 3


def test_validate_expr_side_uses_parser_and_column_lookup() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"1": 1}]]

    _validator().validate_expr_side(
        sql,
        {"expr": "get_json_object({from}.json_col, '$.key')"},
        expected_scope="from",
        workspace_table_id=1,
        qf_side_label="left",
    )


def test_validate_expr_side_rejects_wrong_scope() -> None:
    with pytest.raises(ForgeError):
        _validator().validate_expr_side(
            FakeForgeQueryPort(),
            {"expr": "get_json_object({to}.json_col, '$.key')"},
            expected_scope="from",
            workspace_table_id=1,
            qf_side_label="left",
        )
