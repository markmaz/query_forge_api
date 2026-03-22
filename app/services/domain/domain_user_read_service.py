from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_result_rows


class UserDomainReadService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_mode: Optional[str] = None) -> None:
        del metadata_mode
        self._sql = sql or ForgeMetaSQL()

    def list_domain_users(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        sql = """
        SELECT
          udm.user_id AS user_id,
          u.email AS email,
          CONCAT_WS(' ', NULLIF(u.first_name,''), NULLIF(u.last_name,'')) AS display_name,
          udm.can_read AS can_read,
          udm.can_edit AS can_edit,
          udm.created_at AS created_at,
          NULL AS updated_at
        FROM user_domain_mapping udm
        JOIN domain d
          ON d.id = udm.domain_id
        AND d.workspace_id = :ws
        AND d.is_active = 1
        LEFT JOIN users u
          ON u.user_id = udm.user_id
        WHERE d.id = :did
        ORDER BY display_name, udm.user_id
        """
        rows = self._sql.execute_query_mappings(sql, {"ws": workspace_id, "did": int(domain_id)})
        return serialize_result_rows([dict(r) for r in rows])

    def list_user_domains(self, *, workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
        sql = """
        SELECT
          d.id,
          d.name,
          d.kind,
          d.description,
          (
            SELECT COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)
            FROM domain_workspace_table dwt2
            JOIN workspace_table wt ON wt.id = dwt2.workspace_table_id
            WHERE dwt2.domain_id = d.id
            ORDER BY dwt2.is_primary DESC, dwt2.sort_order ASC, wt.id ASC
            LIMIT 1
          ) AS primary_table_name,
          d.column_name_policy,
          udm.can_edit
        FROM user_domain_mapping udm
        JOIN domain d
          ON d.id = udm.domain_id
        AND d.workspace_id = :ws
        AND d.is_active = 1
        WHERE udm.user_id = :user_id
          AND udm.can_read = 1
        ORDER BY d.name
        """
        rows = self._sql.execute_query_mappings(sql, {"ws": workspace_id, "user_id": user_id})
        payload = []
        for row in rows:
            shaped = dict(row)
            shaped["model_table_id"] = None
            shaped["model_table_name"] = shaped.get("primary_table_name")
            payload.append(shaped)
        return serialize_result_rows(payload)
