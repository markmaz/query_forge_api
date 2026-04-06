from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services.planner.value_normalizers.country import normalize_country_values, resolve_country_from_db
from tests._support.fakes import FakeForgeQueryPort


def test_country_normalize_iso2_direct() -> None:
    assert normalize_country_values("us") == ["US"]
    assert normalize_country_values("MX") == ["MX"]


def test_country_normalize_name() -> None:
    assert normalize_country_values("United States") == ["US"]


def test_country_normalize_punct() -> None:
    assert normalize_country_values("U.S.") == ["US"]


def test_country_normalize_code3() -> None:
    assert normalize_country_values("USA") == ["US"]


def test_country_normalize_list_dedupe() -> None:
    assert normalize_country_values(["US", "United States", "u.s."]) == ["US"]


def test_country_normalize_unknown() -> None:
    assert normalize_country_values("Wakanda") == []


def test_resolve_country_from_db_returns_none_when_reference_tables_are_unavailable() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [SQLAlchemyError("missing country_reference"), SQLAlchemyError("missing ref_country")]

    assert resolve_country_from_db(sql, "United States") is None


def test_resolve_country_from_db_surfaces_unexpected_query_errors() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [AssertionError("unexpected country lookup failure")]

    with pytest.raises(AssertionError, match="unexpected country lookup failure"):
        resolve_country_from_db(sql, "United States")
