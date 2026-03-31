from __future__ import annotations

from typing import Optional

from app.ports.sql_executor import ForgeQueryPort


class ColumnNamePolicyService:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def get_policy(self, *, workspace_id: str, domain_id: Optional[int]) -> str:
        if not domain_id:
            return "DEDUP_PRIMARY_FIRST"

        rows = self._sql.execute_query_mappings(
            """
            SELECT column_name_policy
            FROM domain
            WHERE id = :did AND workspace_id = :ws AND is_active = 1
            LIMIT 1
            """,
            {"did": int(domain_id), "ws": workspace_id},
        )
        if not rows:
            return "DEDUP_PRIMARY_FIRST"

        value = (rows[0].get("column_name_policy") or "DEDUP_PRIMARY_FIRST").strip().upper()
        return value if value in {"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"} else "DEDUP_PRIMARY_FIRST"
