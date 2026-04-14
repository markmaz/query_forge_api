from __future__ import annotations

from typing import Any, Dict, Optional

from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_result_rows


class BuilderTableFeedService:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def list_domain_tables(self, *, workspace_id: str, user_id: str, domain_id: Optional[int]) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT DISTINCT
              wt.id AS workspace_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_label,
              wt.catalog_name,
              wt.schema_name,
              wt.table_name,
              wt.full_name,
              wt.variant_code,
              wt.is_qe
            FROM user_domain_mapping udm
            JOIN domain d
              ON d.id = udm.domain_id
             AND d.workspace_id = :ws
             AND d.is_active = 1
             AND udm.user_id = :user_id
             AND udm.can_read = 1
             AND (:domain_id IS NULL OR d.id = :domain_id)
            JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :ws
            ORDER BY COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name), wt.full_name
            """,
            {
                "ws": workspace_id,
                "user_id": user_id,
                "domain_id": int(domain_id) if domain_id is not None else None,
            },
        )
        payload_rows = []
        for row in rows:
            shaped = dict(row)
            shaped["model_table_id"] = shaped.get("workspace_table_id")
            shaped["model_table_name"] = shaped.get("table_label")
            payload_rows.append(shaped)
        return {"rows": serialize_result_rows(payload_rows)}
