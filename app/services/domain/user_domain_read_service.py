from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import METADATA_SOURCE_MODE
from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_result_rows


class UserDomainReadService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_mode: Optional[str] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._metadata_mode = str(metadata_mode or METADATA_SOURCE_MODE or "legacy").strip().lower() or "legacy"

    def list_user_domains(self, *, workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
        if self._metadata_mode == "workspace":
            sql = """
              SELECT
                d.id,
                d.name,
                d.model_table_id,
                (
                  SELECT COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)
                  FROM domain_workspace_table dwt2
                  JOIN workspace_table wt ON wt.id = dwt2.workspace_table_id
                  WHERE dwt2.domain_id = d.id
                  ORDER BY dwt2.is_primary DESC, dwt2.sort_order ASC, wt.id ASC
                  LIMIT 1
                ) AS model_table_name,
                d.description,
                d.column_name_policy,
                udm.can_edit
              FROM user_domain_mapping udm
              JOIN domain d ON d.id = udm.domain_id
              WHERE d.workspace_id = :ws
                AND d.is_active = 1
                AND udm.user_id = :user_id
                AND udm.can_read = 1
              ORDER BY d.name
              """
            rows = self._sql.execute_query_mappings(sql, {"ws": workspace_id, "user_id": user_id})
            return serialize_result_rows([dict(r) for r in rows])

        sql = """
          SELECT
            d.id,
            d.name,
          d.model_table_id,
          mt.name AS model_table_name,
          d.description,
          d.column_name_policy,
          udm.can_edit
          FROM user_domain_mapping udm
          JOIN domain d ON d.id = udm.domain_id
          LEFT JOIN model_table mt ON mt.id = d.model_table_id
          WHERE d.workspace_id = :ws
            AND d.is_active = 1
            AND udm.user_id = :user_id
            AND udm.can_read = 1
          ORDER BY d.name
          """
        rows = self._sql.execute_query_mappings(sql, {"ws": workspace_id, "user_id": user_id})
        return serialize_result_rows([dict(r) for r in rows])
