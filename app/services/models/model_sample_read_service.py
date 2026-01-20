from __future__ import annotations

import json
from typing import Any, Dict, List

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class ModelColumnSampleReadService:
    def __init__(self, *, sql: SQLExecutor | None = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def sample_column_values(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        workspace_table_id: int,
        column_name: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        did = int(domain_id)
        wtid = int(workspace_table_id)
        limit = int(limit)
        col = (column_name or "").strip()

        if did <= 0:
            raise ServiceError("domain_id is required", status_code=400)
        if wtid <= 0:
            raise ServiceError("workspace_table_id is required", status_code=400)
        if not col:
            raise ServiceError("column_name is required", status_code=400)

        # 1) Validate: user can read this domain in this workspace
        # 2) Validate: workspace_table is mapped to this domain
        # 3) Get domain.model_table_id
        sql_domain = """
        SELECT d.id, d.model_table_id
        FROM domain d
        JOIN user_domain_mapping udm
          ON udm.domain_id = d.id
         AND udm.user_id = :uid
         AND udm.can_read = 1
        JOIN domain_workspace_table dwt
          ON dwt.domain_id = d.id
         AND dwt.workspace_table_id = :wtid
        WHERE d.workspace_id = :ws
          AND d.is_active = 1
          AND d.id = :did
        LIMIT 1
        """

        drows = self._sql.execute_query_mappings(
            sql_domain,
            {"ws": workspace_id, "uid": user_id, "did": did, "wtid": wtid},
        )
        drow = drows[0] if drows else None

        if not drow:
            raise ServiceError("Domain/table not accessible", status_code=403)

        mtid = drow.get("model_table_id")
        if not mtid:
            raise ServiceError("Domain is missing model_table_id", status_code=400)

            # 4) Read sample from model_column
            sql_col = """
            SELECT
              mc.model_table_id,
              mt.name AS model_table_name,
              mc.column_name,
              mc.sample_values_json,
              mc.sample_stats_json,
              mc.sample_ran_at,
              mc.sample_error
            FROM model_column mc
            JOIN model_table mt ON mt.id = mc.model_table_id
            WHERE mc.model_table_id = :mtid
              AND mc.column_name = :col
            LIMIT 1
            """

        rows = self._sql.execute_query_mappings(
            sql_col,
            {"mtid": int(mtid), "col": col},
        )
        row = rows[0] if rows else None

        if not row:
            raise ServiceError("Model column not found", status_code=404)

        sample_values: List[Any] = []
        raw = row.get("sample_values_json") or "[]"
        try:
            v = json.loads(raw)
            if isinstance(v, list):
                sample_values = v[: max(0, limit)]
        except Exception:
            sample_values = []

        return {
            "domainId": did,
            "workspaceTableId": wtid,
            "modelTableId": int(row["model_table_id"]),
            "modelTableName": row.get("model_table_name"),
            "columnName": row.get("column_name"),
            "values": sample_values,
            "sampleStatsJson": row.get("sample_stats_json"),
            "sampleRanAt": row.get("sample_ran_at"),  # jsonify_dict will isoformat it
            "error": row.get("sample_error"),
        }
