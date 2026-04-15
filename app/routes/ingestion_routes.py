# app/routes/ingestion_routes.py
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app, g, request
from flask_restx import Namespace, fields

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QF_INGESTION_STALE_GUARD_ENABLED, QF_INGESTION_STALE_SECONDS
from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from flask_restx import Resource
from app.services.analytics.metadata_provider_factory import MetadataProviderFactory
from app.services.analytics.runtime_registry import build_runtime_registry
from app.services.tenancy.datasource_resolver_service import WorkspaceDatasourceResolverService
from app.tasks.ingestion_tasks import (
    _get_sync_service,
    _run_sync_and_update_record,
    sync_metadata_task,
)

logger = logging.getLogger(__name__)

ingestion_ns = Namespace("ingestion", description="Metadata ingestion management")

_sync_request = ingestion_ns.model(
    "SyncRequest",
    {
        "datasource": fields.String(
            required=False,
            description="Datasource name (optional; defaults to the datasource bound to X-Workspace-Id)",
            example="primary",
        ),
        "catalog": fields.String(description="Catalog (optional)", example="main"),
        "schema": fields.String(required=True, description="Schema to sync", example="sales"),
        "table_names": fields.List(fields.String, description="Optional table filter"),
        "run_profiling": fields.Boolean(default=False, description="Run column profiling"),
        "run_enrichment": fields.Boolean(default=False, description="Run AI dictionary enrichment"),
        "overwrite_descriptions": fields.Boolean(
            default=False,
            description="Force overwrite existing table/column descriptions",
        ),
    },
)

_job_response = ingestion_ns.model(
    "JobResponse",
    {"job_id": fields.String(description="Ingestion run ID (Celery task ID)")},
)

_run_model = ingestion_ns.model(
    "IngestionRun",
    {
        "id":              fields.String(),
        "datasource":      fields.String(),
        "catalog":         fields.String(),
        "schema_name":     fields.String(),
        "status":          fields.String(),
        "tables_total":    fields.Integer(),
        "tables_done":     fields.Integer(),
        "tables_failed":   fields.Integer(),
        "tables_created":  fields.Integer(),
        "tables_updated":  fields.Integer(),
        "columns_total":   fields.Integer(),
        "columns_done":    fields.Integer(),
        "columns_failed":  fields.Integer(),
        "columns_created": fields.Integer(),
        "columns_updated": fields.Integer(),
        "current_phase":   fields.String(),
        "current_table":   fields.String(),
        "current_column":  fields.String(),
        "error":           fields.String(),
        "started_at":      fields.String(),
        "completed_at":    fields.String(),
    },
)


_schemas_response = ingestion_ns.model(
    "SchemasResponse",
    {"schemas": fields.List(fields.String, description="Available schema names")},
)

_cancel_response = ingestion_ns.model(
    "CancelResponse",
    {
        "id": fields.String(),
        "canceled": fields.Boolean(),
        "status": fields.String(),
        "message": fields.String(),
    },
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _get_celery_task_state(task_id: str) -> str:
    return str(sync_metadata_task.AsyncResult(task_id).state or "").upper()


def _task_id_in_worker_queues(task_id: str) -> bool:
    """Best-effort worker queue check for brokers without a results backend."""
    inspector = sync_metadata_task.app.control.inspect(timeout=0.8)
    snapshots = (
        inspector.active() or {},
        inspector.reserved() or {},
        inspector.scheduled() or {},
    )

    for snapshot in snapshots:
        for entries in snapshot.values():
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                candidate_ids = [
                    entry.get("id"),
                    entry.get("uuid"),
                ]
                request_payload = entry.get("request")
                if isinstance(request_payload, dict):
                    candidate_ids.extend(
                        [
                            request_payload.get("id"),
                            request_payload.get("uuid"),
                            request_payload.get("task_id"),
                        ]
                    )
                if any(str(candidate or "") == task_id for candidate in candidate_ids):
                    return True
    return False


def _maybe_mark_stale_run_failed(mysql: ForgeMetaSQL, row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("id") or "").strip()
    status = str(row.get("status") or "").strip().lower()
    if not run_id or status != "running" or not QF_INGESTION_STALE_GUARD_ENABLED:
        return row

    started_at = _to_utc(row.get("started_at"))
    if not started_at:
        return row

    age_seconds = int((_utcnow() - started_at).total_seconds())
    if age_seconds < int(QF_INGESTION_STALE_SECONDS):
        return row

    task_state = _get_celery_task_state(run_id)
    if task_state in {"STARTED", "RETRY"}:
        return row
    if _task_id_in_worker_queues(run_id):
        return row

    error = (
        "Marked failed automatically: stale ingestion run with no active Celery task "
        f"(state={task_state or 'UNKNOWN'}, age_seconds={age_seconds})"
    )
    with mysql.transaction() as tx:
        tx.execute_write(
            """
UPDATE ingestion_run
SET status = 'failed',
    current_phase = 'failed',
    error = :error,
    completed_at = :completed_at
WHERE id = :run_id
  AND status = 'running'
""",
                {
                    "run_id": run_id,
                    "error": error[:2000],
                    "completed_at": _utcnow(),
                },
            )
        refreshed = tx.execute_query_mappings(
            "SELECT * FROM ingestion_run WHERE id = :id",
            {"id": run_id},
        )
    if refreshed:
        logger.warning("Auto-failed stale ingestion run id=%s state=%s age_seconds=%s", run_id, task_state, age_seconds)
        return refreshed[0]
    return row


def _build_run_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("id") or "").strip()
    status = str(row.get("status") or "").strip().lower()
    started_at = _to_utc(row.get("started_at"))
    age_seconds = int((_utcnow() - started_at).total_seconds()) if started_at else None
    task_state = _get_celery_task_state(run_id) if run_id else "UNKNOWN"
    in_worker_queues = _task_id_in_worker_queues(run_id) if run_id else False
    stale_candidate = bool(
        QF_INGESTION_STALE_GUARD_ENABLED
        and status == "running"
        and age_seconds is not None
        and age_seconds >= int(QF_INGESTION_STALE_SECONDS)
        and task_state not in {"STARTED", "RETRY"}
        and not in_worker_queues
    )
    return {
        "id": run_id,
        "status": status,
        "celery_state": task_state,
        "in_worker_queues": in_worker_queues,
        "age_seconds": age_seconds,
        "stale_guard_enabled": bool(QF_INGESTION_STALE_GUARD_ENABLED),
        "stale_threshold_seconds": int(QF_INGESTION_STALE_SECONDS),
        "stale_candidate": stale_candidate,
        "run": _serialize_run(row),
    }


def _is_terminal_status(status: str) -> bool:
    return (status or "").strip().lower() in {"completed", "failed", "canceled", "cancelled"}


def _resolve_workspace_bound_datasource_name() -> str | None:
    workspace_id = str(getattr(g, "workspace_id", "") or request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        return None

    resolved = WorkspaceDatasourceResolverService().resolve_for_workspace(
        workspace_id=workspace_id,
        require_active=True,
    )
    if not resolved:
        return None

    return str(resolved.datasource_slug or resolved.datasource_name or "").strip() or None


def _resolve_requested_or_workspace_datasource(requested_name: str | None) -> str | None:
    requested = str(requested_name or "").strip()
    if requested:
        return requested
    return _resolve_workspace_bound_datasource_name()


def _serialize_run(row: dict) -> dict:
    return {
        "id":              str(row.get("id") or ""),
        "datasource":      str(row.get("datasource") or ""),
        "catalog":         row.get("catalog"),
        "schema_name":     str(row.get("schema_name") or ""),
        "status":          str(row.get("status") or ""),
        "tables_total":    int(row.get("tables_total") or 0),
        "tables_done":     int(row.get("tables_done") or 0),
        "tables_failed":   int(row.get("tables_failed") or 0),
        "tables_created":  int(row.get("tables_created") or 0),
        "tables_updated":  int(row.get("tables_updated") or 0),
        "columns_total":   int(row.get("columns_total") or 0),
        "columns_done":    int(row.get("columns_done") or 0),
        "columns_failed":  int(row.get("columns_failed") or 0),
        "columns_created": int(row.get("columns_created") or 0),
        "columns_updated": int(row.get("columns_updated") or 0),
        "current_phase":   (str(row.get("current_phase") or "").strip() or None),
        "current_table":   (str(row.get("current_table") or "").strip() or None),
        "current_column":  (str(row.get("current_column") or "").strip() or None),
        "error":           row.get("error"),
        "started_at":      str(row.get("started_at") or ""),
        "completed_at":    str(row.get("completed_at") or "") or None,
    }


@ingestion_ns.route("/sync")
class IngestionSync(Resource):

    @ingestion_ns.doc("start_sync")
    @ingestion_ns.expect(_sync_request)
    @ingestion_ns.response(202, "Sync job enqueued", _job_response)
    @ingestion_ns.response(400, "Bad request — schema is required or datasource is unknown")
    @ingestion_ns.response(401, "Unauthorised")
    @ingestion_ns.response(403, "Forbidden — admin role required")
    @token_required
    @require_access("ingestion", role="admin")
    def post(self):
        body = request.get_json(silent=True) or {}
        schema = (body.get("schema") or "").strip()
        if not schema:
            return {"error": "'schema' is required"}, 400

        datasource = _resolve_requested_or_workspace_datasource(body.get("datasource"))
        if not datasource:
            return {
                "error": "No datasource provided and the current workspace has no bound datasource",
            }, 400
        catalog = body.get("catalog") or None
        table_names = body.get("table_names") or None
        run_profiling = bool(body.get("run_profiling", False))
        run_enrichment = bool(body.get("run_enrichment", False))
        overwrite_descriptions = bool(body.get("overwrite_descriptions", False))
        workspace_id = str(getattr(g, "workspace_id", "") or "").strip() or None

        # Validate that the requested datasource is actually registered before
        # writing the run row or enqueueing the task.  This prevents zombie runs
        # (stuck in "running" forever) caused by typos or probing requests, and
        # avoids leaking the list of registered datasource names via the error
        # field of a completed-failed run.
        registry = build_runtime_registry(
            fallback_registry=current_app.extensions.get("analytics_registry"),
        )
        known = {ds["name"] for ds in registry.list_datasources()}
        if datasource not in known:
            return {"error": "Unknown datasource"}, 400

        run_id = str(uuid.uuid4())
        mysql = ForgeMetaSQL()

        # Insert the run record and enqueue the Celery task inside a single
        # try/except so that a Celery broker failure causes the run to be marked
        # "failed" immediately rather than being left in "running" state forever.
        with mysql.transaction() as tx:
            tx.execute_write(
                """
INSERT INTO ingestion_run
  (id, datasource, catalog, schema_name, table_names,
   run_profiling, run_enrichment, status, started_at)
VALUES
  (:id, :datasource, :catalog, :schema_name, :table_names,
   :run_profiling, :run_enrichment, 'running', :started_at)
""",
                {
                    "id": run_id,
                    "datasource": datasource,
                    "catalog": catalog,
                    "schema_name": schema,
                    "table_names": json.dumps(table_names) if table_names else None,
                    "run_profiling": int(run_profiling),
                    "run_enrichment": int(run_enrichment),
                    "started_at": datetime.now(timezone.utc),
                },
            )

        try:
            sync_metadata_task.apply_async(
                kwargs={
                    "run_id": run_id,
                    "datasource": datasource,
                    "catalog": catalog,
                    "schema": schema,
                    "workspace_id": workspace_id,
                    "table_names": table_names,
                    "run_profiling": run_profiling,
                    "run_enrichment": run_enrichment,
                    "overwrite_descriptions": overwrite_descriptions,
                    "profiling_options": None,
                },
                task_id=run_id,
            )
        except (OSError, RuntimeError, ValueError):
            logger.exception("Failed to enqueue sync_metadata_task for run %s", run_id)
            logger.warning(
                "Falling back to inline metadata sync for run %s because task enqueue failed",
                run_id,
            )
            try:
                _run_sync_and_update_record(
                    run_id=run_id,
                    datasource=datasource,
                    catalog=catalog,
                    schema=schema,
                    workspace_id=workspace_id,
                    table_names=table_names,
                    run_profiling=run_profiling,
                    run_enrichment=run_enrichment,
                    overwrite_descriptions=overwrite_descriptions,
                    profiling_options=None,
                    sync_service=_get_sync_service(),
                    mysql=mysql,
                )
            except (ForgeError, OSError, RuntimeError, TypeError, ValueError):
                logger.exception("Inline fallback sync failed for run %s", run_id)
                # Mark the run as failed so it is not stuck in "running" state.
                with mysql.transaction() as tx:
                    tx.execute_write(
                        """
UPDATE ingestion_run
SET status = 'failed',
    error  = :error,
    completed_at = :completed_at
WHERE id = :run_id
""",
                        {
                            "run_id": run_id,
                            "error": "Failed to enqueue background task or execute inline fallback",
                            "completed_at": datetime.now(timezone.utc),
                        },
                    )
                return {"error": "Failed to start sync job"}, 500

        return {"job_id": run_id}, 202


@ingestion_ns.route("/status/<string:job_id>")
class IngestionStatus(Resource):

    @ingestion_ns.doc("get_status")
    @ingestion_ns.response(200, "Run status", _run_model)
    @ingestion_ns.response(404, "Not found")
    @ingestion_ns.response(403, "Forbidden")
    @token_required
    @require_access("ingestion", role="admin")
    def get(self, job_id: str):
        mysql = ForgeMetaSQL()
        with mysql.transaction() as tx:
            rows = tx.execute_query_mappings(
                "SELECT * FROM ingestion_run WHERE id = :id",
                {"id": job_id},
            )
        if not rows:
            return {"error": "Ingestion run not found"}, 404
        row = _maybe_mark_stale_run_failed(mysql, rows[0])
        return _serialize_run(row), 200


@ingestion_ns.route("/diagnostics/<string:job_id>")
class IngestionDiagnostics(Resource):

    @ingestion_ns.doc("get_diagnostics")
    @ingestion_ns.response(200, "Ingestion run diagnostics")
    @ingestion_ns.response(403, "Forbidden — admin role required")
    @ingestion_ns.response(404, "Not found")
    @token_required
    @require_access("ingestion", role="admin")
    def get(self, job_id: str):
        mysql = ForgeMetaSQL()
        with mysql.transaction() as tx:
            rows = tx.execute_query_mappings(
                "SELECT * FROM ingestion_run WHERE id = :id",
                {"id": job_id},
            )
        if not rows:
            return {"error": "Ingestion run not found"}, 404

        row = _maybe_mark_stale_run_failed(mysql, rows[0])
        return _build_run_diagnostics(row), 200


@ingestion_ns.route("/cancel/<string:job_id>")
class IngestionCancel(Resource):

    @ingestion_ns.doc("cancel_run")
    @ingestion_ns.response(200, "Run canceled", _cancel_response)
    @ingestion_ns.response(403, "Forbidden — admin role required")
    @ingestion_ns.response(404, "Not found")
    @token_required
    @require_access("ingestion", role="admin")
    def post(self, job_id: str):
        mysql = ForgeMetaSQL()
        with mysql.transaction() as tx:
            rows = tx.execute_query_mappings(
                "SELECT * FROM ingestion_run WHERE id = :id",
                {"id": job_id},
            )
        if not rows:
            return {"error": "Ingestion run not found"}, 404

        row = rows[0]
        status = str(row.get("status") or "")
        if _is_terminal_status(status):
            return {
                "id": str(row.get("id") or job_id),
                "canceled": False,
                "status": status.lower(),
                "message": "Run already in terminal status",
                "diagnostics": _build_run_diagnostics(row),
            }, 200

        revoke_ok = True
        try:
            sync_metadata_task.AsyncResult(job_id).revoke(terminate=True, signal="SIGTERM")
        except (OSError, RuntimeError, ValueError):
            revoke_ok = False
            logger.exception("Failed to revoke ingestion Celery task id=%s", job_id)

        with mysql.transaction() as tx:
            tx.execute_write(
                """
UPDATE ingestion_run
SET status = 'canceled',
    current_phase = 'canceled',
    error = :error,
    completed_at = :completed_at
WHERE id = :run_id
  AND status NOT IN ('completed', 'failed', 'canceled', 'cancelled')
""",
                {
                    "run_id": job_id,
                    "error": "Canceled by operator",
                    "completed_at": _utcnow(),
                },
            )
            refreshed = tx.execute_query_mappings(
                "SELECT * FROM ingestion_run WHERE id = :id",
                {"id": job_id},
            )

        final_row = refreshed[0] if refreshed else row
        return {
            "id": str(final_row.get("id") or job_id),
            "canceled": True,
            "status": str(final_row.get("status") or "").lower(),
            "message": "Cancellation requested" if revoke_ok else "Canceled in DB; Celery revoke call failed",
            "diagnostics": _build_run_diagnostics(final_row),
        }, 200


@ingestion_ns.route("/history")
class IngestionHistory(Resource):

    @ingestion_ns.doc("get_history")
    @ingestion_ns.response(200, "Recent runs", [_run_model])
    @ingestion_ns.response(403, "Forbidden")
    @token_required
    @require_access("ingestion", role="admin")
    def get(self):
        mysql = ForgeMetaSQL()
        with mysql.transaction() as tx:
            rows = tx.execute_query_mappings(
                "SELECT * FROM ingestion_run ORDER BY started_at DESC LIMIT 20",
            )
        return [_serialize_run(r) for r in rows], 200


@ingestion_ns.route("/schemas")
class IngestionSchemas(Resource):

    @token_required
    @require_access("ingestion", role="admin")
    @ingestion_ns.doc(
        "list_schemas",
        params={
            "datasource": "Datasource name (optional; defaults to the datasource bound to X-Workspace-Id)",
            "catalog": "Catalog/database context (optional)",
        },
    )
    @ingestion_ns.response(200, "Schema list", _schemas_response)
    @ingestion_ns.response(400, "Bad request — datasource missing and workspace has no bound datasource")
    @ingestion_ns.response(403, "Forbidden — admin role required")
    @ingestion_ns.response(404, "Datasource not found")
    @ingestion_ns.response(503, "Analytics registry not available")
    @ingestion_ns.marshal_with(_schemas_response)
    def get(self):
        """List schemas available in a configured analytics datasource."""
        datasource_name = _resolve_requested_or_workspace_datasource(
            request.args.get("datasource"),
        )
        if not datasource_name:
            ingestion_ns.abort(
                400,
                "datasource parameter is required unless the current workspace has a bound datasource",
            )

        catalog = (request.args.get("catalog") or "").strip() or None

        registry = build_runtime_registry(
            fallback_registry=current_app.extensions.get("analytics_registry"),
        )
        if not registry.list_datasources():
            ingestion_ns.abort(503, "Analytics registry not available")

        try:
            executor = registry.get(datasource_name)
        except KeyError:
            ingestion_ns.abort(404, "Datasource not found")

        try:
            provider = MetadataProviderFactory.create(executor.get_dialect(), executor)
            schemas = provider.list_schemas(catalog)
        except (ForgeError, OSError, RuntimeError, TypeError, ValueError):
            logger.exception(
                "Schema discovery failed: datasource=%s catalog=%s",
                datasource_name,
                catalog,
            )
            ingestion_ns.abort(500, "Schema discovery failed")

        return {"schemas": schemas}
