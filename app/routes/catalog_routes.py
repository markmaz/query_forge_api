from __future__ import annotations

import inspect
import json
import logging

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy import text

from app.adapters.mysql_sql_executor import engine
from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.services.catalog import catalog_pipeline_service
from app.services.catalog.catalog_context import CatalogContextBuilder
from app.services.catalog.catalog_pipeline_service import CatalogPipelineService
from app.services.catalog.catalog_unmapped_tables_read_service import UnmappedTablesReadService
from app.services.recon.workspace_recon_read_service import CatalogReconReadService
from app.services.recon.workspace_recon_service import CatalogReconService, ReconQuery

logger = logging.getLogger(__name__)
catalog_ns = Namespace("catalog", description="Catalog admin (snapshot + reconciliation)")

logger.info("CatalogPipelineService module: %s", catalog_pipeline_service.__file__)
logger.info("CatalogPipelineService attrs: %s", [a for a in dir(CatalogPipelineService) if "sync" in a])
logger.info("CatalogPipelineService source:\n%s", inspect.getsource(CatalogPipelineService))
def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400


def _get_workspace_id_from_header() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ServiceError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id


def _recon_svc() -> CatalogReconReadService:
    # recon is computed on read; just inject the service that runs the SQL
    return CatalogReconReadService(recon=CatalogReconService())

def _unmapped_svc() -> UnmappedTablesReadService:
    return UnmappedTablesReadService()

@catalog_ns.route("/samples")
class CatalogSamples(Resource):
    @token_required
    def post(self):
        """
        POST /catalog/samples
        headers:
          - X-Workspace-Id
        query:
          - schema=asset
          - max_tables=50 (optional)
          - only_missing=true (default)
          - timeout_s=12
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            schema_name = (request.args.get("schema") or "asset").strip()
            max_tables = request.args.get("max_tables")
            only_missing = (request.args.get("only_missing") or "true").strip().lower() not in ("0", "false", "no")
            timeout_s = int((request.args.get("timeout_s") or "12").strip())

            max_tables_i = int(max_tables) if (max_tables or "").strip() else None

            ctx = CatalogContextBuilder().build(workspace_id)
            result = CatalogPipelineService(sql=ctx.sql_exec).capture_table_samples(
                workspace_id=workspace_id,
                schema_name=schema_name,
                catalog_name=None,
                limit_rows=10,
                max_tables=max_tables_i,
                only_missing=only_missing,
                statement_timeout_s=timeout_s,
            )
            return result, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Catalog samples failed")
            return {"error": "Catalog samples failed"}, 500


@catalog_ns.route("/table-sample")
class CatalogTableSample(Resource):
    @token_required
    def get(self):
        """
        GET /catalog/table-sample?workspace_table_id=123
        headers:
          - X-Workspace-Id   (used only to validate ownership in query)
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            wt_id = int((request.args.get("workspace_table_id") or "").strip())

            with engine.connect() as conn:
                row = conn.execute(
                    text("""
SELECT id, full_name, sample_rows_json, sample_ran_at, sample_error
FROM workspace_table
WHERE id=:id AND workspace_id=:ws
LIMIT 1
"""),
                    {"id": wt_id, "ws": workspace_id},
                ).mappings().first()

            if not row:
                return {"error": "Not found"}, 404

            rows_json = row.get("sample_rows_json") or "[]"
            try:
                rows = json.loads(rows_json)
            except Exception:
                rows = []

            return {
                "workspace_table_id": int(row["id"]),
                "full_name": str(row["full_name"]),
                "ran_at": (row.get("sample_ran_at").isoformat() if row.get("sample_ran_at") else None),
                "error": row.get("sample_error"),
                "rows": rows,
            }, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Fetch table sample failed")
            return {"error": "Fetch table sample failed"}, 500
        
@catalog_ns.route("/sync")
class CatalogSync(Resource):
    @token_required
    def post(self):
        """
        POST /catalog/sync
        headers:
          - X-Workspace-Id
        query:
          - schema=asset (optional)
          - catalog=<name> (optional; default discovered via current_catalog())
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            schema_name = (request.args.get("schema") or "asset").strip()
            catalog_name = (request.args.get("catalog") or "").strip() or None

            ctx = CatalogContextBuilder().build(workspace_id)
            result = CatalogPipelineService(sql=ctx.sql_exec).sync_snapshot(
                workspace_id=workspace_id,
                schema_name=schema_name,
                catalog_name=catalog_name,
                sample_rows=True
            )
            return result, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Catalog sync failed")
            return {"error": "Catalog sync failed"}, 500


@catalog_ns.route("/recon")
class CatalogRecon(Resource):
    @token_required
    def get(self):
        """
        GET /catalog/recon
        headers:
          - X-Workspace-Id
        query:
          - status=...
          - logical_table_name=...
          - limit=200
          - offset=0
        """
        try:
            workspace_id = _get_workspace_id_from_header()

            status = (request.args.get("status") or "").strip() or None
            logical = (request.args.get("logical_table_name") or "").strip() or None
            limit = int((request.args.get("limit") or "200").strip())
            offset = int((request.args.get("offset") or "0").strip())

            rows = _recon_svc().list_recon(
                ReconQuery(
                    workspace_id=workspace_id,
                    status=status,
                    logical_table_name=logical,
                    limit=limit,
                    offset=offset,
                )
            )

            return {"rows": rows}, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Fetch recon failed")
            return {"error": "Fetch recon failed"}, 500


@catalog_ns.route("/recon/counts")
class CatalogReconCounts(Resource):
    @token_required
    def get(self):
        """
        GET /catalog/recon/counts
        headers:
          - X-Workspace-Id
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            counts = _recon_svc().counts_by_status(workspace_id=workspace_id)
            return {"counts": counts}, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Recon counts failed")
            return {"error": "Recon counts failed"}, 500

@catalog_ns.route("/unmapped-tables")
class CatalogUnmappedTables(Resource):
    @token_required
    def get(self):
        """
        GET /catalog/unmapped-tables
        headers:
          - X-Workspace-Id
        query:
          - schema=asset (optional)
          - q=...        (optional search across full_name/table_name/variant_code)
          - limit=200
          - offset=0
        """
        try:
            workspace_id = _get_workspace_id_from_header()

            schema_name = (request.args.get("schema") or "").strip() or None
            q = (request.args.get("q") or "").strip() or None
            limit = int((request.args.get("limit") or "200").strip())
            offset = int((request.args.get("offset") or "0").strip())

            payload = _unmapped_svc().list_unmapped_tables(
                workspace_id=workspace_id,
                schema_name=schema_name,
                q=q,
                limit=limit,
                offset=offset,
            )
            return payload, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Fetch unmapped tables failed")
            return {"error": "Fetch unmapped tables failed"}, 500