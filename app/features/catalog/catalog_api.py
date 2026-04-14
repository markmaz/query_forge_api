from __future__ import annotations

import json
import logging

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy import text

from app.adapters.mysql_sql_executor import engine
from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.recon.workspace_recon_read_service import WorkspaceReconReadService
from app.services.recon.workspace_recon_service import ReconQuery, WorkspaceReconService
from app.services.workspace_inventory.column_sample_write_service import ColumnSampleWriteService
from app.services.workspace_inventory.unmapped_workspace_tables_read_service import UnmappedWorkspaceTablesReadService
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder
from app.services.workspace_inventory.workspace_inventory_pipeline_service import WorkspacePipelineService

from .service import catalog_feature_service

logger = logging.getLogger(__name__)

catalog_ns = Namespace("catalog", description="Catalog admin (snapshot + reconciliation)")


def _error_response(exc: ForgeError):
    return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400


def _catalog_recon_service() -> WorkspaceReconReadService:
    return WorkspaceReconReadService(recon=WorkspaceReconService())


def _catalog_unmapped_service() -> UnmappedWorkspaceTablesReadService:
    return UnmappedWorkspaceTablesReadService()


@catalog_ns.route("/samples")
class CatalogSamples(Resource):
    @token_required
    @require_access("catalog", role="admin")
    def post(self):
        try:
            workspace_id = catalog_feature_service.extract_workspace_id()
            schema_name = (request.args.get("schema") or "asset").strip()
            max_tables_raw = (request.args.get("max_tables") or "").strip()
            max_tables = int(max_tables_raw) if max_tables_raw else None
            only_missing = (request.args.get("only_missing") or "true").strip().lower() not in {
                "0",
                "false",
                "no",
            }
            timeout_s = catalog_feature_service.int_arg(request.args.get("timeout_s"), default=12)

            ctx = WorkspaceSqlContextBuilder().build(workspace_id)
            payload = ColumnSampleWriteService(sql=ctx.sql_exec).refresh_model_samples(
                workspace_id=workspace_id,
                schema_name=schema_name,
                per_column_limit=10,
                max_tables=max_tables,
                active_only=only_missing,
                statement_timeout_s=timeout_s,
            )
            return payload, 200
        except ForgeError as exc:
            return _error_response(exc)
        except Exception:
            logger.exception("Catalog samples failed")
            return {"error": "Catalog samples failed"}, 500


@catalog_ns.route("/table-sample")
class CatalogTableSample(Resource):
    @token_required
    @require_access("catalog")
    def get(self):
        try:
            workspace_id = catalog_feature_service.extract_workspace_id()
            workspace_table_id = catalog_feature_service.int_arg(request.args.get("workspace_table_id"), default=-1)

            with engine.connect() as conn:
                row = (
                    conn.execute(
                        text(
                            """
SELECT id, full_name, sample_rows_json, sample_ran_at, sample_error
FROM workspace_table
WHERE id=:id AND workspace_id=:ws
LIMIT 1
"""
                        ),
                        {"id": workspace_table_id, "ws": workspace_id},
                    )
                    .mappings()
                    .first()
                )

            if not row:
                return {"error": "Not found"}, 404

            raw_rows = row.get("sample_rows_json") or "[]"
            try:
                parsed_rows = json.loads(raw_rows)
            except Exception:
                parsed_rows = []

            return {
                "workspace_table_id": int(row["id"]),
                "full_name": str(row["full_name"]),
                "ran_at": row.get("sample_ran_at").isoformat() if row.get("sample_ran_at") else None,
                "error": row.get("sample_error"),
                "rows": parsed_rows,
            }, 200
        except ForgeError as exc:
            return _error_response(exc)
        except Exception:
            logger.exception("Fetch table sample failed")
            return {"error": "Fetch table sample failed"}, 500


@catalog_ns.route("/sync")
class CatalogSync(Resource):
    @token_required
    @require_access("catalog", role="admin")
    def post(self):
        try:
            workspace_id = catalog_feature_service.extract_workspace_id()
            schema_name = (request.args.get("schema") or "asset").strip()
            catalog_name = (request.args.get("catalog") or "").strip() or None

            ctx = WorkspaceSqlContextBuilder().build(workspace_id)
            payload = WorkspacePipelineService(sql=ctx.sql_exec).sync_snapshot(
                workspace_id=workspace_id,
                schema_name=schema_name,
                catalog_name=catalog_name,
            )
            return payload, 200
        except ForgeError as exc:
            return _error_response(exc)
        except Exception:
            logger.exception("Catalog sync failed")
            return {"error": "Catalog sync failed"}, 500


@catalog_ns.route("/recon")
class CatalogRecon(Resource):
    @token_required
    @require_access("catalog")
    def get(self):
        try:
            workspace_id = catalog_feature_service.extract_workspace_id()
            rows = _catalog_recon_service().list_recon(
                ReconQuery(
                    workspace_id=workspace_id,
                    status=(request.args.get("status") or "").strip() or None,
                    logical_table_name=(request.args.get("logical_table_name") or "").strip() or None,
                    limit=catalog_feature_service.int_arg(request.args.get("limit"), default=200),
                    offset=catalog_feature_service.int_arg(request.args.get("offset"), default=0),
                )
            )
            return {"rows": rows}, 200
        except ForgeError as exc:
            return _error_response(exc)
        except Exception:
            logger.exception("Fetch recon failed")
            return {"error": "Fetch recon failed"}, 500


@catalog_ns.route("/recon/counts")
class CatalogReconCounts(Resource):
    @token_required
    @require_access("catalog")
    def get(self):
        try:
            workspace_id = catalog_feature_service.extract_workspace_id()
            return {"counts": _catalog_recon_service().counts_by_status(workspace_id=workspace_id)}, 200
        except ForgeError as exc:
            return _error_response(exc)
        except Exception:
            logger.exception("Recon counts failed")
            return {"error": "Recon counts failed"}, 500


@catalog_ns.route("/unmapped-tables")
class CatalogUnmappedTables(Resource):
    @token_required
    @require_access("catalog")
    def get(self):
        try:
            workspace_id = catalog_feature_service.extract_workspace_id()
            payload = _catalog_unmapped_service().list_unmapped_tables(
                workspace_id=workspace_id,
                schema_name=(request.args.get("schema") or "").strip() or None,
                q=(request.args.get("q") or "").strip() or None,
                limit=catalog_feature_service.int_arg(request.args.get("limit"), default=200),
                offset=catalog_feature_service.int_arg(request.args.get("offset"), default=0),
            )
            return payload, 200
        except ForgeError as exc:
            return _error_response(exc)
        except Exception:
            logger.exception("Fetch unmapped tables failed")
            return {"error": "Fetch unmapped tables failed"}, 500
