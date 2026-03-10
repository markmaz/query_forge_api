from __future__ import annotations

import importlib
import sys
import types

import app.config as config


def _load_catalog_tasks(monkeypatch):
    monkeypatch.setattr(config, "MYSQL_URL", "mysql://local/test", raising=False)
    fake_catalog = types.ModuleType("app.services.catalog")
    fake_sync = types.ModuleType("app.services.catalog.catalog_sync")
    fake_sync.reconcile_columns = lambda **k: {"recon": True}
    fake_sync.sync_dbx_catalog_snapshot = lambda **k: {"snap": True}
    sys.modules["app.services.catalog"] = fake_catalog
    sys.modules["app.services.catalog.catalog_sync"] = fake_sync
    mod = importlib.import_module("app.tasks.catalog_tasks")
    return importlib.reload(mod)


def test_build_forge_executor(monkeypatch):
    catalog_tasks = _load_catalog_tasks(monkeypatch)

    class _Ctx:
        sql_exec = "exec"

    class _Builder:
        def build(self, workspace_id: str):
            assert workspace_id == "ws1"
            return _Ctx()

    monkeypatch.setattr(catalog_tasks, "WorkspaceContextBuilder", _Builder)
    exec = catalog_tasks.build_forge_executor("ws1")
    assert exec == "exec"


def test_sync_workspace_catalog(monkeypatch):
    catalog_tasks = _load_catalog_tasks(monkeypatch)
    monkeypatch.setattr(catalog_tasks, "create_engine", lambda *a, **k: "engine")
    monkeypatch.setattr(catalog_tasks, "build_forge_executor", lambda ws: "exec")

    res = catalog_tasks.sync_workspace_catalog.run("ws1", schema_name="asset")
    assert res["snapshot"]["snap"] is True
    assert res["reconcile"]["recon"] is True
