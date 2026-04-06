"""Phase 2 — tests for app/services/query_forge/sql_utils.py."""
from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError


class TestLiteralSql:
    def test_none_becomes_null(self):
        from app.services.query_forge.sql_utils import literal_sql
        assert literal_sql(None) == "NULL"

    def test_bool_true(self):
        from app.services.query_forge.sql_utils import literal_sql
        assert literal_sql(True) == "TRUE"

    def test_bool_false(self):
        from app.services.query_forge.sql_utils import literal_sql
        assert literal_sql(False) == "FALSE"

    def test_int(self):
        from app.services.query_forge.sql_utils import literal_sql
        assert literal_sql(42) == "42"

    def test_float(self):
        from app.services.query_forge.sql_utils import literal_sql
        assert literal_sql(3.14) == "3.14"

    def test_string_escaped(self):
        from app.services.query_forge.sql_utils import literal_sql
        assert literal_sql("O'Brien") == "'O''Brien'"

    def test_string_backslash_escaped(self):
        from app.services.query_forge.sql_utils import literal_sql
        assert literal_sql("a\\b") == "'a\\\\b'"


class TestRenderSql:
    def test_no_params_returns_sql_unchanged(self):
        from app.services.query_forge.sql_utils import render_sql
        assert render_sql("SELECT 1", {}) == "SELECT 1"

    def test_replaces_named_params(self):
        from app.services.query_forge.sql_utils import render_sql
        sql = "SELECT * FROM t WHERE id = :p0 AND name = :p1"
        result = render_sql(sql, {"p0": 5, "p1": "Alice"})
        assert result == "SELECT * FROM t WHERE id = 5 AND name = 'Alice'"

    def test_list_param_rendered_as_in_clause(self):
        from app.services.query_forge.sql_utils import render_sql
        sql = "SELECT * FROM t WHERE id IN :p0"
        result = render_sql(sql, {"p0": [1, 2, 3]})
        assert result == "SELECT * FROM t WHERE id IN (1, 2, 3)"

    def test_unknown_param_key_left_in_place(self):
        from app.services.query_forge.sql_utils import render_sql
        sql = "SELECT :p0"
        result = render_sql(sql, {})
        assert result == "SELECT :p0"


class TestSafeIdent:
    def test_valid_ident(self):
        from app.services.query_forge.sql_utils import safe_ident
        assert safe_ident("my_col") == "my_col"

    def test_invalid_ident_raises(self):
        from app.services.query_forge.sql_utils import safe_ident
        with pytest.raises(ForgeError):
            safe_ident("bad-col!")

    def test_empty_raises(self):
        from app.services.query_forge.sql_utils import safe_ident
        with pytest.raises(ForgeError):
            safe_ident("")


class TestSafeAlias:
    def test_simple_alias(self):
        from app.services.query_forge.sql_utils import safe_alias
        assert safe_alias("my_alias") == "my_alias"

    def test_alias_with_spaces_backtick_quoted(self):
        from app.services.query_forge.sql_utils import safe_alias
        result = safe_alias("my alias")
        assert result == "`my alias`"

    def test_none_raises(self):
        from app.services.query_forge.sql_utils import safe_alias
        with pytest.raises(ForgeError):
            safe_alias(None)  # type: ignore[arg-type]

    def test_empty_raises(self):
        from app.services.query_forge.sql_utils import safe_alias
        with pytest.raises(ForgeError):
            safe_alias("")


class TestDpIdent:
    def test_simple_name(self):
        from app.services.query_forge.sql_utils import dp_ident
        assert dp_ident("revenue") == "__dp_revenue"

    def test_spaces_replaced_with_underscore(self):
        from app.services.query_forge.sql_utils import dp_ident
        assert dp_ident("claim type") == "__dp_claim_type"

    def test_digit_prefix_handled(self):
        from app.services.query_forge.sql_utils import dp_ident
        result = dp_ident("1metric")
        assert result.startswith("__dp_c_")

    def test_empty_fallback(self):
        from app.services.query_forge.sql_utils import dp_ident
        assert dp_ident("") == "__dp_col"


class TestColExpr:
    def test_invalid_workspace_table_id_maps_to_forge_error(self):
        from app.services.query_forge.sql_utils import col_expr
        with pytest.raises(ForgeError, match="Invalid workspaceTableId"):
            col_expr(
                {"columnName": "age", "workspaceTableId": "bad"},
                {},
                {},
                {},
                {},
                False,
                "t1",
                {},
            )

    def test_invalid_rewrite_workspace_table_id_is_ignored(self):
        from app.services.query_forge.sql_utils import col_expr
        result = col_expr(
            {"columnName": "age", "workspaceTableId": "bad"},
            {},
            {},
            {"age": "__dp_age"},
            {},
            True,
            "t1",
            {},
        )
        assert result == "__dp_age"

    def test_unexpected_rewrite_workspace_table_id_error_propagates(self):
        from app.services.query_forge.sql_utils import col_expr

        class _BadInt:
            def __int__(self):
                raise AssertionError("int bug")

        with pytest.raises(AssertionError, match="int bug"):
            col_expr(
                {"columnName": "age", "workspaceTableId": _BadInt()},
                {},
                {},
                {"age": "__dp_age"},
                {},
                True,
                "t1",
                {},
            )
