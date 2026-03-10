# tests/analytics/test_ingestion_routes.py
from __future__ import annotations

import json
from unittest.mock import MagicMock


import app.routes.ingestion_routes as ingestion_routes_module


def _mock_token(monkeypatch, *, is_admin: bool = True):
    from app.decorators import security
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


_VALID_HEADERS = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}


def test_post_sync_returns_job_id(client, monkeypatch):
    _mock_token(monkeypatch)

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
        headers=_VALID_HEADERS,
        data=json.dumps({"datasource": "primary", "schema": "sales",
                         "run_profiling": False, "run_enrichment": False}),
    )

    assert resp.status_code == 202
    assert "job_id" in resp.json
    assert captured["kwargs"]["overwrite_descriptions"] is False


def test_post_sync_forwards_overwrite_flag(client, monkeypatch):
    _mock_token(monkeypatch)

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

    resp = client.post(
        "/api/v1/ingestion/sync",
        headers=_VALID_HEADERS,
        data=json.dumps({"datasource": "primary"}),
    )

    assert resp.status_code == 400


def test_post_sync_falls_back_to_inline_when_enqueue_fails(client, monkeypatch):
    _mock_token(monkeypatch)

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
    return registry, executor


def test_get_schemas_returns_list(client, monkeypatch):
    _mock_token(monkeypatch)

    registry, executor = _make_registry_with_executor()
    mock_provider = MagicMock()
    mock_provider.list_schemas.return_value = ["asset", "raw"]

    import app.routes.ingestion_routes as _mod
    monkeypatch.setattr(_mod.MetadataProviderFactory, "create", lambda _dialect, _exec: mock_provider)

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

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
    mock_provider = MagicMock()
    mock_provider.list_schemas.return_value = ["sales"]

    import app.routes.ingestion_routes as _mod
    monkeypatch.setattr(_mod.MetadataProviderFactory, "create", lambda _dialect, _exec: mock_provider)

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

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


def test_get_schemas_unknown_datasource(client, monkeypatch):
    _mock_token(monkeypatch)

    registry = MagicMock()
    registry.get.side_effect = KeyError("unknown")

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=unknown",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 404


def test_get_schemas_provider_failure(client, monkeypatch):
    _mock_token(monkeypatch)

    registry, executor = _make_registry_with_executor()
    mock_provider = MagicMock()
    mock_provider.list_schemas.side_effect = RuntimeError("connection refused")

    import app.routes.ingestion_routes as _mod
    monkeypatch.setattr(_mod.MetadataProviderFactory, "create", lambda _dialect, _exec: mock_provider)

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=primary",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 500


def test_get_schemas_requires_admin(client, monkeypatch):
    _mock_token(monkeypatch, is_admin=False)

    registry, _ = _make_registry_with_executor()

    with client.application.app_context():
        client.application.extensions["analytics_registry"] = registry

    resp = client.get(
        "/api/v1/ingestion/schemas?datasource=primary",
        headers=_VALID_HEADERS,
    )

    assert resp.status_code == 403
