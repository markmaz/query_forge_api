from __future__ import annotations

from app.adapters.analytics.snowflake_executor import (
    _is_missing_warehouse_error,
    _rewrite_named_params_for_snowflake,
)


def test_rewrite_named_params_for_snowflake_converts_sqlalchemy_binds() -> None:
    sql = "select * from t where a = :p1 and b in (:p2, :p3)"
    out = _rewrite_named_params_for_snowflake(sql, {"p1": 1, "p2": 2, "p3": 3})
    assert out == "select * from t where a = %(p1)s and b in (%(p2)s, %(p3)s)"


def test_rewrite_named_params_for_snowflake_preserves_non_binds() -> None:
    sql = "select ':not_a_bind' as x, col from t where id = :p10"
    out = _rewrite_named_params_for_snowflake(sql, {"p1": 1, "p10": 10})
    assert out == "select ':not_a_bind' as x, col from t where id = %(p10)s"


def test_is_missing_warehouse_error_by_errno() -> None:
    class _Exc(Exception):
        errno = 606

    assert _is_missing_warehouse_error(_Exc("x")) is True


def test_is_missing_warehouse_error_by_message() -> None:
    assert _is_missing_warehouse_error(Exception("No active warehouse selected in the current session")) is True
