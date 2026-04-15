from __future__ import annotations

from contextlib import contextmanager

import pytest

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


def test_command_service_create_returns_none_when_insert_result_has_no_lastrowid() -> None:
    class _Repository:
        @contextmanager
        def transaction(self):
            yield object()

        def ensure_domain(self, *_args, **_kwargs):
            return None

        def ensure_tables_in_domain(self, *_args, **_kwargs):
            return None

        def find_existing_join(self, *_args, **_kwargs):
            return None

        def insert_join(self, *_args, **_kwargs):
            return object()

    class _Validator:
        def validate_join_expr_columns(self, *_args, **_kwargs):
            return None

    service = DomainJoinCommandService(repository=_Repository(), validator=_Validator())

    out = service.create_join(workspace_id="ws", payload=_payload())

    assert out == {"ok": True, "id": None}


def test_command_service_create_surfaces_unexpected_lastrowid_errors() -> None:
    class _BadResult:
        @property
        def lastrowid(self):
            raise AssertionError("unexpected insert result bug")

    class _Repository:
        @contextmanager
        def transaction(self):
            yield object()

        def ensure_domain(self, *_args, **_kwargs):
            return None

        def ensure_tables_in_domain(self, *_args, **_kwargs):
            return None

        def find_existing_join(self, *_args, **_kwargs):
            return None

        def insert_join(self, *_args, **_kwargs):
            return _BadResult()

    class _Validator:
        def validate_join_expr_columns(self, *_args, **_kwargs):
            return None

    service = DomainJoinCommandService(repository=_Repository(), validator=_Validator())

    with pytest.raises(AssertionError, match="unexpected insert result bug"):
        service.create_join(workspace_id="ws", payload=_payload())
