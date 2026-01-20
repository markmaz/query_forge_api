from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class DomainColumnSampleReadService:
    """
    Fast sample values read from MySQL cache:
      model_column.sample_values_json / sample_stats_json / sample_ran_at / sample_error

    We still accept workspace_table_id because:
      - it anchors the request to the user's accessible table (domain membership)
      - it resolves model_table_id to find the correct model_column row
    """

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def sample_column_values(
        self,
        *,
        workspace_id: str,
        user_id: str,
        workspace_table_id: int,
        column_name: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        limit = int(limit)
        col = (column_name or "").strip()
        if not col:
            raise ServiceError("column_name is required", status_code=400)

        # 1) Ensure the user can read this workspace_table via domain membership
        # 2) Resolve workspace_table.full_name + model_table_id
        sql_ws = """
            SELECT
            wt.id,
            wt.workspace_id,
            wt.full_name,
            wt.model_table_id
            FROM workspace_table wt
            WHERE wt.id = :wtid
            AND wt.workspace_id = :ws
            AND wt.exists_in_dbx = 1
            AND EXISTS (
                SELECT 1
                FROM user_domain_mapping udm
                JOIN domain d
                ON d.id = udm.domain_id
                AND d.workspace_id = :ws
                AND d.is_active = 1
                JOIN domain_workspace_table dwt
                ON dwt.domain_id = d.id
                AND dwt.workspace_table_id = wt.id
                WHERE udm.user_id = :uid
                AND udm.can_read = 1
            )
            LIMIT 1
            """
        ws_rows = self._sql.execute_query_mappings(
            sql_ws, {"wtid": int(workspace_table_id), "ws": workspace_id, "uid": user_id}
        )
        ws_row = ws_rows[0] if ws_rows else None

        if not ws_row:
            raise ServiceError("workspace_table not found (or no access)", status_code=404)

        model_table_id = ws_row.get("model_table_id")
        if not model_table_id:
            return {
                "workspace_table_id": int(workspace_table_id),
                "full_name": ws_row.get("full_name"),
                "model_table_id": None,
                "column_name": col,
                "limit": limit,
                "values": [],
                "sample_stats": None,
                "sample_ran_at": None,
                "error": "workspace_table is not mapped to a model_table",
            }

        # Pull the model_column samples for that model_table_id + column_name
        sql_col = """
            SELECT
            mc.sample_values_json,
            mc.sample_stats_json,
            mc.sample_ran_at,
            mc.sample_error
            FROM model_column mc
            WHERE mc.model_table_id = :mtid
            AND mc.column_name = :col
            AND mc.is_active = 1
            LIMIT 1
        """
        mc_rows = self._sql.execute_query_mappings(
            sql_col, {"mtid": int(model_table_id), "col": col}
        )
        mc_row = mc_rows[0] if mc_rows else None

        if not mc_row:
            return {
                "workspace_table_id": int(workspace_table_id),
                "full_name": ws_row.get("full_name"),
                "model_table_id": int(model_table_id),
                "column_name": col,
                "limit": limit,
                "values": [],
                "sample_stats": None,
                "sample_ran_at": None,
                "error": "model_column not found for this model_table_id + column_name",
            }

        if mc_row.get("sample_error"):
            return {
                "workspace_table_id": int(workspace_table_id),
                "full_name": ws_row.get("full_name"),
                "model_table_id": int(model_table_id),
                "column_name": col,
                "limit": limit,
                "values": [],
                "sample_stats": _safe_json_load(mc_row.get("sample_stats_json")),
                "sample_ran_at": mc_row.get("sample_ran_at"),
                "error": mc_row.get("sample_error"),
            }

        values = _safe_json_load(mc_row.get("sample_values_json")) or []
        if not isinstance(values, list):
            values = []

        # trim to requested limit
        values = values[:limit]

        return {
            "workspace_table_id": int(workspace_table_id),
            "full_name": ws_row.get("full_name"),
            "model_table_id": int(model_table_id),
            "column_name": col,
            "limit": limit,
            "values": values,
            "sample_stats": _safe_json_load(mc_row.get("sample_stats_json")),
            "sample_ran_at": mc_row.get("sample_ran_at"),
            "error": None,
        }


def _safe_json_load(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None
