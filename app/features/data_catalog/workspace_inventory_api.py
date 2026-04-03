from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder
from app.services.workspace_inventory.workspace_inventory_pipeline_service import WorkspacePipelineService

logger = logging.getLogger(__name__)

wsinv_ns = Namespace("workspace-inventory", description="Workspace inventory (DBX snapshot cache)")


def _handle_service_error(exc: ForgeError):
    return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400


@wsinv_ns.route("/sync")
class WorkspaceInventorySync(Resource):
    @token_required
    @require_access("catalog", role="admin")
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
