from __future__ import annotations

from datetime import datetime, timedelta

from app.services.workspace_inventory.workspace_snapshot_ensure_service import WorkspaceSnapshotEnsureService
from tests._support.fakes import FakeForgeQueryPort


def test_ensure_runs_snapshot_when_empty(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    service = WorkspaceSnapshotEnsureService(sql=sql)
    called = {}

    monkeypatch.setattr(service, "_run_snapshot", lambda **_kwargs: called.setdefault("ok", True))
    service.ensure(workspace_id="ws1", schema_name="asset")
    assert called["ok"] is True


def test_ensure_skips_when_fresh(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"ok": 1}],
        [{"max_seen": datetime.now()}],
    ]
    service = WorkspaceSnapshotEnsureService(sql=sql)
    called = {}
    monkeypatch.setattr(service, "_run_snapshot", lambda **_kwargs: called.setdefault("ok", True))
    service.ensure(workspace_id="ws1", schema_name="asset", min_fresh_age_minutes=30)
    assert called == {}


def test_ensure_runs_when_missing_last_seen(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"ok": 1}],
        [{"max_seen": None}],
    ]
    service = WorkspaceSnapshotEnsureService(sql=sql)
    called = {}
    monkeypatch.setattr(service, "_run_snapshot", lambda **_kwargs: called.setdefault("ok", True))
    service.ensure(workspace_id="ws1", schema_name="asset")
    assert called["ok"] is True


def test_ensure_runs_when_stale(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"ok": 1}],
        [{"max_seen": datetime.now() - timedelta(minutes=30)}],
    ]
    service = WorkspaceSnapshotEnsureService(sql=sql)
    called = {}
    monkeypatch.setattr(service, "_run_snapshot", lambda **_kwargs: called.setdefault("ok", True))
    service.ensure(workspace_id="ws1", schema_name="asset", min_fresh_age_minutes=10)
    assert called["ok"] is True
