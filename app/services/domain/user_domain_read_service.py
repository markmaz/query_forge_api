from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_result_rows


class UserDomainReadService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_user_domains(self, *, workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
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
