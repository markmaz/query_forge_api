from __future__ import annotations

import pytest

import app.services.analytics.runtime_registry as runtime_registry
from app.services.analytics.registry import AnalyticsDatasourceRegistry


def test_build_runtime_registry_skips_expected_runtime_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Catalog:
        def __init__(self, *, sql=None):
            del sql

        def load_all_executor_configs(self):
            return {"broken": {"type": "snowflake"}}

    monkeypatch.setattr(runtime_registry, "DatasourceCatalogService", _Catalog)
    monkeypatch.setattr(
        runtime_registry.ExecutorFactory,
        "create",
        staticmethod(lambda _ds_type, _cfg: (_ for _ in ()).throw(RuntimeError("factory failed"))),
    )

    fallback = AnalyticsDatasourceRegistry({})

    out = runtime_registry.build_runtime_registry(fallback_registry=fallback)

    assert out is fallback


def test_build_runtime_registry_surfaces_unexpected_factory_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Catalog:
        def __init__(self, *, sql=None):
            del sql

        def load_all_executor_configs(self):
            return {"broken": {"type": "snowflake"}}

    monkeypatch.setattr(runtime_registry, "DatasourceCatalogService", _Catalog)
    monkeypatch.setattr(
        runtime_registry.ExecutorFactory,
        "create",
        staticmethod(lambda _ds_type, _cfg: (_ for _ in ()).throw(AssertionError("unexpected factory bug"))),
    )

    with pytest.raises(AssertionError, match="unexpected factory bug"):
        runtime_registry.build_runtime_registry()
