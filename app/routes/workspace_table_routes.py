from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource
from sqlalchemy import text

from app.adapters.mysql_sql_executor import engine
from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)

workspace_tables_ns = Namespace("workspace-tables", description="Workspace table operations")


def _workspace_id_from_header() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ForgeError("X-Workspace-Id header is required", status_code=400)
    return workspace_id


def _handle_error(exc: ForgeError):
    return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400


@workspace_tables_ns.route("/<int:workspace_table_id>/columns")
class WorkspaceTableColumns(ForgeResource):
    @token_required
    @require_access("workspaces")
    def get(self, workspace_table_id: int):
        try:
            workspace_id = _workspace_id_from_header()
            query = """
                SELECT
                    wc.id,
                    wc.workspace_table_id,
                    wc.column_name,
                    wc.data_type,
                    wc.ordinal_position
                FROM workspace_column wc
                JOIN workspace_table wt
                  ON wt.id = wc.workspace_table_id
                WHERE wc.workspace_table_id = :wtid
                  AND wt.workspace_id = :ws
                ORDER BY wc.ordinal_position, wc.column_name
            """
            with engine.connect() as conn:
                result = conn.execute(text(query), {"wtid": int(workspace_table_id), "ws": workspace_id})
                rows = result.mappings().all()
            return {"rows": [dict(row) for row in rows]}, 200
        except ForgeError as exc:
            return _handle_error(exc)
        except Exception:
            logger.exception("Workspace table columns fetch failed")
            return {"error": "Workspace table columns fetch failed"}, 500
