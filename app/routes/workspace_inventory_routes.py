from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import bool_arg, get_workspace_id_from_header, int_arg
from app.services.models.model_snapshot_import_service import ModelSnapshotImportService
from app.services.recon.workspace_recon_read_service import WorkspaceReconReadService
from app.services.recon.workspace_recon_service import ReconQuery, WorkspaceReconService
from app.services.workspace_inventory.unmapped_workspace_tables_read_service import UnmappedWorkspaceTablesReadService
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder
from app.services.workspace_inventory.workspace_inventory_pipeline_service import WorkspacePipelineService

logger = logging.getLogger(__name__)
wsinv_ns = Namespace("workspace-inventory", description="Workspace inventory (DBX snapshot cache)")


def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400


# If Recon services are cheap, this is fine; otherwise hoist to module-level singletons.
def _recon_svc() -> WorkspaceReconReadService:
    return WorkspaceReconReadService(recon=WorkspaceReconService())


@wsinv_ns.route("/sync")
class WorkspaceInventorySync(Resource):
    @token_required
    def post(self):
        """
        POST /workspace-inventory/sync?schema=asset&catalog=&force=true|false

        headers:
          - X-Workspace-Id

        Notes:
          - If force=true, runs a Databricks snapshot sync for workspace_table/workspace_column
          - Always refreshes model snapshot (model_table/model_column)
        """
        try:
            workspace_id = get_workspace_id_from_header()
            ctx = WorkspaceContextBuilder().build(workspace_id)
            schema_name = (request.args.get("schema") or "asset").strip()
            catalog_name = (request.args.get("catalog") or "").strip() or None
            force = bool_arg("force", default=False)

            snapshot_result = None
            if force:
                snapshot_result = WorkspacePipelineService(sql=ctx.sql_exec).sync_snapshot(
                    workspace_id=workspace_id,
                    schema_name=schema_name,
                    catalog_name=catalog_name,
                )

            svc = ModelSnapshotImportService(
                sql=ctx.sql_exec,
            )
            res = svc.import_snapshot(deactivate_missing=True)
            return {"ok": True, "workspaceSnapshot": snapshot_result, **res.__dict__}

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Workspace inventory sync failed")
            return {"error": "Workspace inventory sync failed"}, 500


@wsinv_ns.route("/unmapped-tables")
class WorkspaceInventoryUnmapped(Resource):
    @token_required
    def get(self):
        """
        GET /workspace-inventory/unmapped-tables?schema=&q=&limit=&offset=
        headers:
          - X-Workspace-Id
        """
        try:
            workspace_id = get_workspace_id_from_header()
            schema_name = (request.args.get("schema") or "").strip() or None
            q = (request.args.get("q") or "").strip() or None
            limit = int_arg("limit", 200)
            offset = int_arg("offset", 0)

            payload = UnmappedWorkspaceTablesReadService().list_unmapped_tables(
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
            logger.exception("Unmapped tables fetch failed")
            return {"error": "Unmapped tables fetch failed"}, 500


@wsinv_ns.route("/recon")
class WorkspaceInventoryRecon(Resource):
    @token_required
    def get(self):
        """
        GET /workspace-inventory/recon?status=&logical_table_name=&limit=&offset=
        headers:
          - X-Workspace-Id
        """
        try:
            workspace_id = get_workspace_id_from_header()

            status = (request.args.get("status") or "").strip() or None
            if status:
                status = status.upper()

            logical = (request.args.get("logical_table_name") or "").strip() or None
            limit = int_arg("limit", 200)
            offset = int_arg("offset", 0)

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


@wsinv_ns.route("/recon/counts")
class WorkspaceInventoryReconCounts(Resource):
    @token_required
    def get(self):
        """
        GET /workspace-inventory/recon/counts
        headers:
          - X-Workspace-Id
        """
        try:
            workspace_id = get_workspace_id_from_header()
            counts = _recon_svc().counts_by_status(workspace_id=workspace_id)
            return {"counts": counts}, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Recon counts failed")
            return {"error": "Recon counts failed"}, 500
