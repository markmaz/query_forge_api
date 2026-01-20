import logging

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy import text

from app.adapters.mysql_sql_executor import engine
from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError

logger = logging.getLogger(__name__)

workspace_tables_ns = Namespace("workspace-tables", description="Workspace table operations")


def _get_workspace_id_from_header() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ServiceError("X-Workspace-Id header is required", status_code=400)
    return workspace_id


@workspace_tables_ns.route("/<int:workspace_table_id>/columns")
class WorkspaceTableColumns(Resource):
    @token_required
    def get(self, workspace_table_id: int):
        """
        GET /workspace-tables/<workspace_table_id>/columns
        Returns columns for a workspace table ordered by ordinal_position.
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            sql = """
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
                rows = conn.execute(text(sql), {"wtid": int(workspace_table_id), "ws": workspace_id}).mappings().all()
            return {"rows": [dict(r) for r in rows]}, 200
        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Workspace table columns fetch failed")
            return {"error": "Workspace table columns fetch failed"}, 500
