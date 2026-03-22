# tests/analytics/test_ingestion_routes.py
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


import app.routes.ingestion_routes as ingestion_routes_module


def _mock_token(monkeypatch, *, is_admin: bool = True, roles: set[str] | None = None):
    from app.decorators import security
    import app.services.rbac_service as rbac_service
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _t: {"sub": "user-1", "username": "user-1", "is_admin": is_admin},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set({"workspace_admin"} if roles is None else roles),
    )


_VALID_HEADERS = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}
_VALID_WORKSPACE_HEADERS = {
    **_VALID_HEADERS,
    "X-Workspace-Id": "ws-1",
}


def _mock_runtime_registry(monkeypatch, registry) -> None:
    monkeypatch.setattr(
        ingestion_routes_module,
        "build_runtime_registry",
        lambda fallback_registry=None: registry,
    )


def _mock_workspace_datasource(monkeypatch, *, slug: str = "workspace-ds") -> None:
    class _Resolved:
        datasource_slug = slug
        datasource_name = "Workspace Datasource"

    monkeypatch.setattr(
        ingestion_routes_module.WorkspaceDatasourceResolverService,
        "resolve_for_workspace",
        lambda self, *, workspace_id, require_active=True: _Resolved(),
    )


def test_post_sync_returns_job_id(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_runtime_registry(monkeypatch, _make_registry_with_executor()[0])

    mock_task_result = MagicMock()
    mock_task_result.id = "celery-task-id-123"

    mock_tx = MagicMock()
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    captured: dict = {}

    def _apply_async(**kwargs):
        captured.update(kwargs)
        return mock_task_result

    monkeypatch.setattr(ingestion_routes_module.sync_metadata_task, "apply_async", _apply_async)

    resp = client.post(
        "/api/v1/ingestion/sync",
        headers=_VALID_WORKSPACE_HEADERS,
        data=json.dumps({"datasource": "primary", "schema": "sales",
                         "run_profiling": False, "run_enrichment": False}),
    )

    assert resp.status_code == 202
    assert "job_id" in resp.json
    assert captured["kwargs"]["workspace_id"] == "ws-1"
    assert captured["kwargs"]["overwrite_descriptions"] is False


def test_get_schemas_allows_workspace_admin_without_legacy_admin_flag(client, monkeypatch):
    _mock_token(monkeypatch, is_admin=False)

    mock_executor = MagicMock()
    mock_executor.get_dialect.return_value = "snowflake"
    mock_registry = MagicMock()
    mock_registry.list_datasources.return_value = [{"name": "workspace-ds"}]
    mock_registry.get.return_value = mock_executor
    _mock_runtime_registry(monkeypatch, mock_registry)
    _mock_workspace_datasource(monkeypatch, slug="workspace-ds")

    mock_provider = MagicMock()
    mock_provider.list_schemas.return_value = ["analytics", "raw"]
    monkeypatch.setattr(
        ingestion_routes_module.MetadataProviderFactory,
        "create",
        lambda dialect, executor: mock_provider,
    )

    resp = client.get(
        "/api/v1/ingestion/schemas?catalog=teds_prod",
        headers=_VALID_WORKSPACE_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json["schemas"] == ["analytics", "raw"]


def test_post_sync_forwards_overwrite_flag(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_runtime_registry(monkeypatch, _make_registry_with_executor()[0])

    mock_task_result = MagicMock()
    mock_task_result.id = "celery-task-id-123"

    mock_tx = MagicMock()
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    captured: dict = {}

    def _apply_async(**kwargs):
        captured.update(kwargs)
        return mock_task_result

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(ingestion_routes_module.sync_metadata_task, "apply_async", _apply_async)

    resp = client.post(
        "/api/v1/ingestion/sync",
        headers=_VALID_HEADERS,
        data=json.dumps(
            {
                "datasource": "primary",
                "schema": "sales",
                "overwrite_descriptions": True,
            }
        ),
    )

    assert resp.status_code == 202
    assert captured["kwargs"]["overwrite_descriptions"] is True


def test_post_sync_requires_schema(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_runtime_registry(monkeypatch, _make_registry_with_executor()[0])

    resp = client.post(
        "/api/v1/ingestion/sync",
        headers=_VALID_HEADERS,
        data=json.dumps({"datasource": "primary"}),
    )

    assert resp.status_code == 400


def test_post_sync_uses_workspace_bound_datasource_when_omitted(client, monkeypatch):
    _mock_token(monkeypatch)
    registry, _executor = _make_registry_with_executor()
    registry.list_datasources.return_value = [{"name": "workspace-ds", "type": "databricks"}]
    _mock_runtime_registry(monkeypatch, registry)
    _mock_workspace_datasource(monkeypatch, slug="workspace-ds")

    mock_task_result = MagicMock()
    mock_task_result.id = "celery-task-id-456"
    mock_tx = MagicMock()
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    captured: dict = {}

    def _apply_async(**kwargs):
        captured.update(kwargs)
        return mock_task_result

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(ingestion_routes_module.sync_metadata_task, "apply_async", _apply_async)

    resp = client.post(
        "/api/v1/ingestion/sync",
        headers=_VALID_WORKSPACE_HEADERS,
        data=json.dumps({"schema": "sales"}),
    )

    assert resp.status_code == 202
    assert captured["kwargs"]["datasource"] == "workspace-ds"
    insert_params = mock_tx.execute_write.call_args.args[1]
    assert insert_params["datasource"] == "workspace-ds"


def test_post_sync_falls_back_to_inline_when_enqueue_fails(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_runtime_registry(monkeypatch, _make_registry_with_executor()[0])

    mock_tx = MagicMock()
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    called = {"inline": False}
    inline_kwargs: dict = {}

    def fake_inline(**kwargs):
        called["inline"] = True
        inline_kwargs.update(kwargs)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(
        ingestion_routes_module.sync_metadata_task,
        "apply_async",
        lambda **_kwargs: (_ for _ in ()).throw(ConnectionRefusedError("broker down")),
    )
    monkeypatch.setattr(ingestion_routes_module, "_get_sync_service", lambda: MagicMock())
    monkeypatch.setattr(ingestion_routes_module, "_run_sync_and_update_record", fake_inline)

    resp = client.post(
        "/api/v1/ingestion/sync",
        headers=_VALID_HEADERS,
        data=json.dumps({"datasource": "primary", "schema": "sales"}),
    )

    assert resp.status_code == 202
    assert "job_id" in resp.json
    assert called["inline"] is True
    assert inline_kwargs["overwrite_descriptions"] is False


def test_post_sync_returns_500_if_enqueue_and_inline_fallback_fail(client, monkeypatch):
    _mock_token(monkeypatch)
    _mock_runtime_registry(monkeypatch, _make_registry_with_executor()[0])

    mock_tx = MagicMock()
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(
        ingestion_routes_module.sync_metadata_task,
        "apply_async",
        lambda **_kwargs: (_ for _ in ()).throw(ConnectionRefusedError("broker down")),
    )
    monkeypatch.setattr(
        ingestion_routes_module,
        "_get_sync_service",
        lambda: (_ for _ in ()).throw(RuntimeError("no service")),
    )

    resp = client.post(
        "/api/v1/ingestion/sync",
        headers=_VALID_HEADERS,
        data=json.dumps({"datasource": "primary", "schema": "sales"}),
    )

    assert resp.status_code == 500
    assert resp.json["error"] == "Failed to start sync job"


def test_get_status_returns_run(client, monkeypatch):
    _mock_token(monkeypatch)

    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.return_value = [{
        "id": "test-id", "datasource": "primary", "schema_name": "sales",
        "catalog": None, "status": "completed",
        "tables_total": 3, "tables_done": 3, "tables_failed": 0,
        "tables_created": 3, "tables_updated": 0,
        "columns_created": 10, "columns_updated": 0,
        "started_at": "2026-03-08T10:00:00",
        "completed_at": "2026-03-08T10:01:00", "error": None,
    }]
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)

    resp = client.get("/api/v1/ingestion/status/test-id", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json["id"] == "test-id"
    assert resp.json["status"] == "completed"


def test_get_status_404_when_not_found(client, monkeypatch):
    _mock_token(monkeypatch)

    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.return_value = []
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)

    resp = client.get("/api/v1/ingestion/status/no-such-id", headers=_VALID_HEADERS)

    assert resp.status_code == 404


def test_get_status_auto_fails_stale_orphaned_run(client, monkeypatch):
    _mock_token(monkeypatch)

    started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    first_row = {
        "id": "test-id",
        "datasource": "primary",
        "schema_name": "sales",
        "catalog": None,
        "status": "running",
        "tables_total": 3,
        "tables_done": 3,
        "columns_total": 10,
        "columns_done": 4,
        "started_at": started_at,
        "completed_at": None,
        "error": None,
    }
    second_row = dict(first_row)
    second_row["status"] = "failed"
    second_row["current_phase"] = "failed"
    second_row["completed_at"] = datetime.now(timezone.utc)
    second_row["error"] = "auto-failed"

    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.side_effect = [[first_row], [second_row]]
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(ingestion_routes_module, "QF_INGESTION_STALE_GUARD_ENABLED", True)
    monkeypatch.setattr(ingestion_routes_module, "QF_INGESTION_STALE_SECONDS", 30)
    monkeypatch.setattr(ingestion_routes_module, "_get_celery_task_state", lambda _task_id: "PENDING")
    monkeypatch.setattr(ingestion_routes_module, "_task_id_in_worker_queues", lambda _task_id: False)

    resp = client.get("/api/v1/ingestion/status/test-id", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json["status"] == "failed"
    assert mock_tx.execute_write.call_count == 1


def test_get_status_does_not_auto_fail_when_task_visible_in_worker_queue(client, monkeypatch):
    _mock_token(monkeypatch)

    started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    row = {
        "id": "test-id",
        "datasource": "primary",
        "schema_name": "sales",
        "catalog": None,
        "status": "running",
        "tables_total": 3,
        "tables_done": 3,
        "columns_total": 10,
        "columns_done": 4,
        "started_at": started_at,
        "completed_at": None,
        "error": None,
    }

    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.return_value = [row]
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(ingestion_routes_module, "QF_INGESTION_STALE_GUARD_ENABLED", True)
    monkeypatch.setattr(ingestion_routes_module, "QF_INGESTION_STALE_SECONDS", 30)
    monkeypatch.setattr(ingestion_routes_module, "_get_celery_task_state", lambda _task_id: "PENDING")
    monkeypatch.setattr(ingestion_routes_module, "_task_id_in_worker_queues", lambda _task_id: True)

    resp = client.get("/api/v1/ingestion/status/test-id", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json["status"] == "running"
    assert mock_tx.execute_write.call_count == 0


def test_get_diagnostics_returns_run_snapshot(client, monkeypatch):
    _mock_token(monkeypatch)

    started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    row = {
        "id": "test-id",
        "datasource": "primary",
        "schema_name": "sales",
        "catalog": None,
        "status": "running",
        "tables_total": 3,
        "tables_done": 2,
        "columns_total": 10,
        "columns_done": 6,
        "started_at": started_at,
        "completed_at": None,
        "error": None,
    }

    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.return_value = [row]
    mock_tx.execute_write.return_value = 0
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(ingestion_routes_module, "_get_celery_task_state", lambda _task_id: "STARTED")
    monkeypatch.setattr(ingestion_routes_module, "_task_id_in_worker_queues", lambda _task_id: True)

    resp = client.get("/api/v1/ingestion/diagnostics/test-id", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json["id"] == "test-id"
    assert resp.json["celery_state"] == "STARTED"
    assert resp.json["in_worker_queues"] is True
    assert "run" in resp.json


def test_get_diagnostics_requires_admin(client, monkeypatch):
    _mock_token(monkeypatch, is_admin=False, roles=set())
    resp = client.get("/api/v1/ingestion/diagnostics/test-id", headers=_VALID_HEADERS)
    assert resp.status_code == 403


def test_cancel_run_marks_running_as_canceled(client, monkeypatch):
    _mock_token(monkeypatch)

    row_running = {
        "id": "test-id",
        "datasource": "primary",
        "schema_name": "sales",
        "catalog": None,
        "status": "running",
        "tables_total": 3,
        "tables_done": 2,
        "columns_total": 10,
        "columns_done": 6,
        "started_at": datetime.now(timezone.utc) - timedelta(minutes=2),
        "completed_at": None,
        "error": None,
    }
    row_canceled = dict(row_running)
    row_canceled["status"] = "canceled"
    row_canceled["current_phase"] = "canceled"
    row_canceled["completed_at"] = datetime.now(timezone.utc)
    row_canceled["error"] = "Canceled by operator"

    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.side_effect = [[row_running], [row_canceled]]
    mock_tx.execute_write.return_value = 1
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)

    revoke_called = {"called": False}

    class _FakeAsyncResult:
        def revoke(self, terminate=False, signal=None):
            revoke_called["called"] = True
            assert terminate is True
            assert signal == "SIGTERM"

    monkeypatch.setattr(
        ingestion_routes_module.sync_metadata_task,
        "AsyncResult",
        lambda _task_id: _FakeAsyncResult(),
    )
    monkeypatch.setattr(ingestion_routes_module, "_get_celery_task_state", lambda _task_id: "REVOKED")
    monkeypatch.setattr(ingestion_routes_module, "_task_id_in_worker_queues", lambda _task_id: False)

    resp = client.post("/api/v1/ingestion/cancel/test-id", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json["canceled"] is True
    assert resp.json["status"] == "canceled"
    assert revoke_called["called"] is True
    assert mock_tx.execute_write.call_count == 1


def test_cancel_run_is_noop_for_terminal_status(client, monkeypatch):
    _mock_token(monkeypatch)

    row = {
        "id": "test-id",
        "datasource": "primary",
        "schema_name": "sales",
        "catalog": None,
        "status": "completed",
        "tables_total": 3,
        "tables_done": 3,
        "columns_total": 10,
        "columns_done": 10,
        "started_at": datetime.now(timezone.utc) - timedelta(minutes=4),
        "completed_at": datetime.now(timezone.utc),
        "error": None,
    }
    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.return_value = [row]
    mock_tx.execute_write.return_value = 0
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)
    monkeypatch.setattr(ingestion_routes_module, "_get_celery_task_state", lambda _task_id: "SUCCESS")
    monkeypatch.setattr(ingestion_routes_module, "_task_id_in_worker_queues", lambda _task_id: False)

    resp = client.post("/api/v1/ingestion/cancel/test-id", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert resp.json["canceled"] is False
    assert resp.json["status"] == "completed"
    assert mock_tx.execute_write.call_count == 0


def test_get_history_returns_list(client, monkeypatch):
    _mock_token(monkeypatch)

    mock_tx = MagicMock()
    mock_tx.execute_query_mappings.return_value = [
        {"id": "r1", "datasource": "primary", "schema_name": "sales",
         "catalog": None, "status": "completed",
         "tables_total": 5, "tables_done": 5, "tables_failed": 0,
         "tables_created": 5, "tables_updated": 0,
         "columns_created": 20, "columns_updated": 0,
         "started_at": "2026-03-08T10:00:00", "completed_at": None, "error": None}
    ]
    mock_mysql = MagicMock()
    mock_mysql.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(ingestion_routes_module, "ForgeMetaSQL", lambda: mock_mysql)

    resp = client.get("/api/v1/ingestion/history", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    assert isinstance(resp.json, list)
    assert len(resp.json) == 1


def test_sync_requires_auth(client):
    resp = client.post(
        "/api/v1/ingestion/sync",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"datasource": "primary", "schema": "sales"}),
    )
    assert resp.status_code == 403


def test_status_requires_auth(client):
    resp = client.get("/api/v1/ingestion/status/some-id")
    assert resp.status_code == 403


def test_history_requires_auth(client):
    resp = client.get("/api/v1/ingestion/history")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/ingestion/schemas
# ---------------------------------------------------------------------------

def _make_registry_with_executor(dialect: str = "databricks"):
    """Return a mock registry whose .get() yields a mock executor."""
    executor = MagicMock()
    executor.get_dialect.return_value = dialect
    registry = MagicMock()
    registry.get.return_value = executor
    registry.list_datasources.return_value = [{"name": "primary", "type": dialect}]
    return registry, executor


def test_get_schemas_returns_list(client, monkeypatch):
    _mock_token(monkeypatch)

    registry, executor = _make_registry_with_executor()
    _mock_runtime_registry(monkeypatch, registry)
    mock_provider = MagicMock()
    mock_provider.list_schemas.return_value = ["asset", "raw"]

    import app.routes.ingestion_routes as _mod
    monkeypatch.setattr(_mod.MetadataProviderFactory, "create", lambda _dialect, _exec: mock_provider)

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=primary",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json["schemas"] == ["asset", "raw"]
    mock_provider.list_schemas.assert_called_once_with(None)


def test_get_schemas_with_catalog(client, monkeypatch):
    _mock_token(monkeypatch)

    registry, executor = _make_registry_with_executor()
    _mock_runtime_registry(monkeypatch, registry)
    mock_provider = MagicMock()
    mock_provider.list_schemas.return_value = ["sales"]

    import app.routes.ingestion_routes as _mod
    monkeypatch.setattr(_mod.MetadataProviderFactory, "create", lambda _dialect, _exec: mock_provider)

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=primary&catalog=main",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json["schemas"] == ["sales"]
    mock_provider.list_schemas.assert_called_once_with("main")


def test_get_schemas_missing_datasource(client, monkeypatch):
    _mock_token(monkeypatch)

    resp = client.get(
        "/api/v1/ingestion/schemas",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 400


def test_get_schemas_uses_workspace_bound_datasource_when_omitted(client, monkeypatch):
    _mock_token(monkeypatch)

    registry, executor = _make_registry_with_executor()
    registry.list_datasources.return_value = [{"name": "workspace-ds", "type": "databricks"}]
    _mock_runtime_registry(monkeypatch, registry)
    _mock_workspace_datasource(monkeypatch, slug="workspace-ds")
    registry.get.side_effect = lambda datasource_name: executor if datasource_name == "workspace-ds" else (_ for _ in ()).throw(KeyError(datasource_name))
    mock_provider = MagicMock()
    mock_provider.list_schemas.return_value = ["asset", "raw"]

    import app.routes.ingestion_routes as _mod
    monkeypatch.setattr(_mod.MetadataProviderFactory, "create", lambda _dialect, _exec: mock_provider)

    resp = client.get(
        "/api/v1/ingestion/schemas",
        headers=_VALID_WORKSPACE_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json["schemas"] == ["asset", "raw"]
    registry.get.assert_called_once_with("workspace-ds")


def test_get_schemas_unknown_datasource(client, monkeypatch):
    _mock_token(monkeypatch)

    registry = MagicMock()
    registry.get.side_effect = KeyError("unknown")
    registry.list_datasources.return_value = [{"name": "known", "type": "databricks"}]
    _mock_runtime_registry(monkeypatch, registry)

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=unknown",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 404


def test_get_schemas_provider_failure(client, monkeypatch):
    _mock_token(monkeypatch)

    registry, executor = _make_registry_with_executor()
    _mock_runtime_registry(monkeypatch, registry)
    mock_provider = MagicMock()
    mock_provider.list_schemas.side_effect = RuntimeError("connection refused")

    import app.routes.ingestion_routes as _mod
    monkeypatch.setattr(_mod.MetadataProviderFactory, "create", lambda _dialect, _exec: mock_provider)

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=primary",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 500


def test_get_schemas_requires_admin(client, monkeypatch):
    _mock_token(monkeypatch, is_admin=False, roles=set())

    registry, _ = _make_registry_with_executor()
    _mock_runtime_registry(monkeypatch, registry)

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=primary",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 403
