"""Tests for app.services.analytics.registry.AnalyticsDatasourceRegistry."""
from __future__ import annotations

import pytest

from app.ports.sql_executor_abc import SQLExecutor
from app.services.analytics.registry import AnalyticsDatasourceRegistry


# ---------------------------------------------------------------------------
# Stub executor for testing
# ---------------------------------------------------------------------------


class _StubExecutor(SQLExecutor):
    def __init__(self, dialect: str = "databricks") -> None:
        self._dialect = dialect

    def execute(self, sql, params=None):
        return []

    def test_connection(self):
        pass

    def get_dialect(self):
        return self._dialect


# ---------------------------------------------------------------------------
# Registry.get
# ---------------------------------------------------------------------------


def test_get_returns_primary_executor():
    executor = _StubExecutor("databricks")
    registry = AnalyticsDatasourceRegistry({"primary": executor})

    result = registry.get("primary")
    assert result is executor


def test_get_defaults_to_primary_when_name_is_none():
    executor = _StubExecutor("databricks")
    registry = AnalyticsDatasourceRegistry({"primary": executor})

    result = registry.get()
    assert result is executor


def test_get_defaults_to_primary_when_name_is_empty_string():
    executor = _StubExecutor("databricks")
    registry = AnalyticsDatasourceRegistry({"primary": executor})

    result = registry.get("")
    assert result is executor


def test_get_returns_named_executor():
    primary = _StubExecutor("databricks")
    legacy = _StubExecutor("mysql")
    registry = AnalyticsDatasourceRegistry({"primary": primary, "legacy": legacy})

    assert registry.get("legacy") is legacy


def test_get_raises_key_error_for_unknown_name():
    registry = AnalyticsDatasourceRegistry({"primary": _StubExecutor()})

    with pytest.raises(KeyError, match="not registered"):
        registry.get("nonexistent")


# ---------------------------------------------------------------------------
# Registry.list_datasources
# ---------------------------------------------------------------------------


def test_list_datasources_returns_name_and_type():
    registry = AnalyticsDatasourceRegistry(
        {
            "primary": _StubExecutor("databricks"),
            "legacy": _StubExecutor("mysql"),
        }
    )

    result = registry.list_datasources()

    assert isinstance(result, list)
    names = {item["name"] for item in result}
    types = {item["type"] for item in result}

    assert names == {"primary", "legacy"}
    assert types == {"databricks", "mysql"}


def test_list_datasources_empty_registry():
    registry = AnalyticsDatasourceRegistry({})
    assert registry.list_datasources() == []


def test_list_datasources_sorted_by_name():
    registry = AnalyticsDatasourceRegistry(
        {
            "zebra": _StubExecutor("snowflake"),
            "alpha": _StubExecutor("databricks"),
        }
    )
    names = [item["name"] for item in registry.list_datasources()]
    assert names == sorted(names)


def test_list_datasources_does_not_expose_extra_fields():
    """list_datasources must only return name and type — no credentials."""
    registry = AnalyticsDatasourceRegistry({"primary": _StubExecutor("databricks")})
    result = registry.list_datasources()

    assert len(result) == 1
    assert set(result[0].keys()) == {"name", "type"}
