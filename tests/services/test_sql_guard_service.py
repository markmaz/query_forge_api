from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.sql_guard_service import (
    assert_no_disallowed_client_sql_fields,
    assert_read_only_sql_statement,
)


def test_assert_no_disallowed_client_sql_fields_rejects_raw_sql_inputs() -> None:
    with pytest.raises(ServiceError) as exc:
        assert_no_disallowed_client_sql_fields({"sql": "SELECT 1", "sqlJson": {"domainId": 1}})
    assert exc.value.status_code == 400


def test_assert_read_only_sql_statement_accepts_select_and_with() -> None:
    assert_read_only_sql_statement("SELECT 1")
    assert_read_only_sql_statement("WITH t AS (SELECT 1) SELECT * FROM t")


def test_assert_read_only_sql_statement_rejects_multi_statement() -> None:
    with pytest.raises(ServiceError) as exc:
        assert_read_only_sql_statement("SELECT 1; SELECT 2")
    assert exc.value.status_code == 400


def test_assert_read_only_sql_statement_rejects_mutating_statement() -> None:
    with pytest.raises(ServiceError) as exc:
        assert_read_only_sql_statement("DELETE FROM users")
    assert exc.value.status_code == 400
