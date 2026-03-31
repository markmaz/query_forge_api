from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.execution.execution_request_validator import ExecutionRequestValidator


def _validator() -> ExecutionRequestValidator:
    return ExecutionRequestValidator(
        assert_no_disallowed_client_sql_fields=lambda payload: None,
        int_from_payload=lambda value, _name: None if value is None else int(value),
        int_from_args=lambda args, name, default: int(args[name]) if args.get(name) else default,
    )


def test_validate_start_defaults_query_builder_from_sql_json() -> None:
    request = _validator().validate_start({"sqlJson": {"domainId": 1}}, {})
    assert request.kind == "query_builder"
    assert request.sql_json == {"domainId": 1}
    assert request.raw_sql is None
    assert request.limit == 200
    assert request.offset == 0


def test_validate_start_accepts_query_builder_sql() -> None:
    request = _validator().validate_start({"rawSql": "SELECT 1", "kind": "query_builder_sql"}, {"limit": "25"})
    assert request.kind == "query_builder_sql"
    assert request.raw_sql == "SELECT 1"
    assert request.limit == 25


def test_validate_start_rejects_missing_payload_shape() -> None:
    with pytest.raises(ForgeError):
        _validator().validate_start({}, {})


def test_validate_start_rejects_sql_json_for_query_builder_sql() -> None:
    with pytest.raises(ForgeError):
        _validator().validate_start({"kind": "query_builder_sql", "rawSql": "SELECT 1", "sqlJson": {"domainId": 1}}, {})
