from __future__ import annotations

from app.services.domain.join.domain_join_command_service import DomainJoinCommandService
from app.services.domain.join.domain_join_expression_parser import DomainJoinExpressionParser
from app.services.domain.join.domain_join_repository import DomainJoinRepository
from app.services.domain.join.domain_join_validator import DomainJoinValidator
from tests._support.fakes import FakeForgeQueryPort


def _payload():
    validator = DomainJoinValidator(expression_parser=DomainJoinExpressionParser())
    return validator.prepare_payload(
        domain_id=1,
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec={
            "on": [
                {
                    "left": {"columnName": "left_col", "workspaceTableId": 1},
                    "right": {"columnName": "right_col", "workspaceTableId": 2},
                }
            ]
        },
        sort_order=0,
    )


def test_command_service_lists_via_repository() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"id": 1}]]
    service = DomainJoinCommandService(
        repository=DomainJoinRepository(sql=sql),
        validator=DomainJoinValidator(expression_parser=DomainJoinExpressionParser()),
    )
    rows = service.list_domain_joins(workspace_id="ws", domain_id=1)
    assert rows == [{"id": 1}]


def test_command_service_create_reactivates_existing_join() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 1}],
        [{"workspace_table_id": 1}, {"workspace_table_id": 2}],
        [{"id": "j1", "is_active": 0}],
    ]
    service = DomainJoinCommandService(
        repository=DomainJoinRepository(sql=sql),
        validator=DomainJoinValidator(expression_parser=DomainJoinExpressionParser()),
    )
    out = service.create_join(workspace_id="ws", payload=_payload())
    assert out == {"ok": True, "id": "j1"}
