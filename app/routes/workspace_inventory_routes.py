from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id, int_arg
from app.services.recon.workspace_recon_read_service import WorkspaceReconReadService
from app.services.recon.workspace_recon_service import ReconQuery, WorkspaceReconService
from app.services.workspace_inventory.unmapped_workspace_tables_read_service import UnmappedWorkspaceTablesReadService
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder
from app.services.workspace_inventory.workspace_inventory_pipeline_service import WorkspacePipelineService

logger = logging.getLogger(__name__)

wsinv_ns = Namespace("workspace-inventory", description="Workspace inventory (DBX snapshot cache)")


def _handle_service_error(exc: ForgeError):
    return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400


def _recon_service() -> WorkspaceReconReadService:
    return WorkspaceReconReadService(recon=WorkspaceReconService())


@wsinv_ns.route("/sync")
class WorkspaceInventorySync(ForgeResource):
    @token_required
    def post(self):
        try:
            workspace_id = extract_workspace_id()
            context = WorkspaceSqlContextBuilder().build(workspace_id)

            schema_name = (request.args.get("schema") or "asset").strip()
            catalog_name = (request.args.get("catalog") or "").strip() or None

            snapshot_result = WorkspacePipelineService(sql=context.sql_exec).sync_snapshot(
                workspace_id=workspace_id,
                schema_name=schema_name,
                catalog_name=catalog_name,
            )
            return {"ok": True, "workspaceSnapshot": snapshot_result}
        except ForgeError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Workspace inventory sync failed")
            return {"error": "Workspace inventory sync failed"}, 500


@wsinv_ns.route("/unmapped-tables")
class WorkspaceInventoryUnmapped(ForgeResource):
    @token_required
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            payload = UnmappedWorkspaceTablesReadService().list_unmapped_tables(
                workspace_id=workspace_id,
                schema_name=(request.args.get("schema") or "").strip() or None,
                q=(request.args.get("q") or "").strip() or None,
                limit=int_arg("limit", 200),
                offset=int_arg("offset", 0),
            )
            return payload, 200
        except ForgeError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Unmapped tables fetch failed")
            return {"error": "Unmapped tables fetch failed"}, 500


@wsinv_ns.route("/recon")
class WorkspaceInventoryRecon(ForgeResource):
    @token_required
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            status = (request.args.get("status") or "").strip() or None
            if status:
                status = status.upper()

            rows = _recon_service().list_recon(
                ReconQuery(
                    workspace_id=workspace_id,
                    status=status,
                    logical_table_name=(request.args.get("logical_table_name") or "").strip() or None,
                    limit=int_arg("limit", 200),
                    offset=int_arg("offset", 0),
                )
            )
            return {"rows": rows}, 200
        except ForgeError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Fetch recon failed")
            return {"error": "Fetch recon failed"}, 500


@wsinv_ns.route("/recon/counts")
class WorkspaceInventoryReconCounts(ForgeResource):
    @token_required
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            counts = _recon_service().counts_by_status(workspace_id=workspace_id)
            return {"counts": counts}, 200
        except ForgeError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Recon counts failed")
            return {"error": "Recon counts failed"}, 500
