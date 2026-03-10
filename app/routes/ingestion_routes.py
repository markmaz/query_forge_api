# app/routes/ingestion_routes.py
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from flask import current_app, g, request
from flask_restx import Namespace, fields

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.decorators.security import token_required
from app.routes.forge_resource import ForgeResource
from app.services.analytics.metadata_provider_factory import MetadataProviderFactory
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
        "datasource": fields.String(required=True, description="Datasource name", example="primary"),
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
class IngestionSync(ForgeResource):

    @ingestion_ns.doc("start_sync")
    @ingestion_ns.expect(_sync_request)
    @ingestion_ns.response(202, "Sync job enqueued", _job_response)
    @ingestion_ns.response(400, "Bad request — schema is required or datasource is unknown")
    @ingestion_ns.response(401, "Unauthorised")
    @ingestion_ns.response(403, "Forbidden — admin role required")
    @token_required
    def post(self):
        # Admin-only: triggering a full metadata sync is a privileged operation.
        if not bool(getattr(g, "is_admin", False)):
            return {"error": "Admin role required"}, 403

        body = request.get_json(silent=True) or {}
        schema = (body.get("schema") or "").strip()
        if not schema:
            return {"error": "'schema' is required"}, 400

        datasource = (body.get("datasource") or "primary").strip()
        catalog = body.get("catalog") or None
        table_names = body.get("table_names") or None
        run_profiling = bool(body.get("run_profiling", False))
        run_enrichment = bool(body.get("run_enrichment", False))
        overwrite_descriptions = bool(body.get("overwrite_descriptions", False))

        # Validate that the requested datasource is actually registered before
        # writing the run row or enqueueing the task.  This prevents zombie runs
        # (stuck in "running" forever) caused by typos or probing requests, and
        # avoids leaking the list of registered datasource names via the error
        # field of a completed-failed run.
        registry = current_app.extensions.get("analytics_registry")
        if registry is not None:
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
                    "started_at": datetime.utcnow(),
                },
            )

        try:
            sync_metadata_task.apply_async(
                kwargs={
                    "run_id": run_id,
                    "datasource": datasource,
                    "catalog": catalog,
                    "schema": schema,
                    "table_names": table_names,
                    "run_profiling": run_profiling,
                    "run_enrichment": run_enrichment,
                    "overwrite_descriptions": overwrite_descriptions,
                    "profiling_options": None,
                },
                task_id=run_id,
            )
        except Exception:
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
                    table_names=table_names,
                    run_profiling=run_profiling,
                    run_enrichment=run_enrichment,
                    overwrite_descriptions=overwrite_descriptions,
                    profiling_options=None,
                    sync_service=_get_sync_service(),
                    mysql=mysql,
                )
            except Exception:
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
                            "completed_at": datetime.utcnow(),
                        },
                    )
                return {"error": "Failed to start sync job"}, 500

        return {"job_id": run_id}, 202


@ingestion_ns.route("/status/<string:job_id>")
class IngestionStatus(ForgeResource):

    @ingestion_ns.doc("get_status")
    @ingestion_ns.response(200, "Run status", _run_model)
    @ingestion_ns.response(404, "Not found")
    @ingestion_ns.response(403, "Forbidden")
    @token_required
    def get(self, job_id: str):
        mysql = ForgeMetaSQL()
        with mysql.transaction() as tx:
            rows = tx.execute_query_mappings(
                "SELECT * FROM ingestion_run WHERE id = :id",
                {"id": job_id},
            )
        if not rows:
            return {"error": "Ingestion run not found"}, 404
        return _serialize_run(rows[0]), 200


@ingestion_ns.route("/history")
class IngestionHistory(ForgeResource):

    @ingestion_ns.doc("get_history")
    @ingestion_ns.response(200, "Recent runs", [_run_model])
    @ingestion_ns.response(403, "Forbidden")
    @token_required
    def get(self):
        mysql = ForgeMetaSQL()
        with mysql.transaction() as tx:
            rows = tx.execute_query_mappings(
                "SELECT * FROM ingestion_run ORDER BY started_at DESC LIMIT 20",
            )
        return [_serialize_run(r) for r in rows], 200


@ingestion_ns.route("/schemas")
class IngestionSchemas(ForgeResource):

    @token_required
    @ingestion_ns.doc(
        "list_schemas",
        params={
            "datasource": "Datasource name (required)",
            "catalog": "Catalog/database context (optional)",
        },
    )
    @ingestion_ns.response(200, "Schema list", _schemas_response)
    @ingestion_ns.response(400, "Bad request — datasource parameter missing")
    @ingestion_ns.response(403, "Forbidden — admin role required")
    @ingestion_ns.response(404, "Datasource not found")
    @ingestion_ns.response(503, "Analytics registry not available")
    @ingestion_ns.marshal_with(_schemas_response)
    def get(self):
        """List schemas available in a configured analytics datasource."""
        if not g.is_admin:
            ingestion_ns.abort(403, "Admin access required")

        datasource_name = (request.args.get("datasource") or "").strip()
        if not datasource_name:
            ingestion_ns.abort(400, "datasource parameter is required")

        catalog = (request.args.get("catalog") or "").strip() or None

        registry = current_app.extensions.get("analytics_registry")
        if not registry:
            ingestion_ns.abort(503, "Analytics registry not available")

        try:
            executor = registry.get(datasource_name)
        except KeyError:
            ingestion_ns.abort(404, "Datasource not found")

        try:
            provider = MetadataProviderFactory.create(executor.get_dialect(), executor)
            schemas = provider.list_schemas(catalog)
        except Exception:
            logger.exception(
                "Schema discovery failed: datasource=%s catalog=%s",
                datasource_name,
                catalog,
            )
            ingestion_ns.abort(500, "Schema discovery failed")

        return {"schemas": schemas}
