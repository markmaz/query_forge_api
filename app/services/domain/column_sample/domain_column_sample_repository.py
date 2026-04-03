from __future__ import annotations

from typing import Any, Dict, Optional

from app.ports.sql_executor import ForgeQueryPort


def load_workspace_column_sample(
    *,
    sql: ForgeQueryPort,
    workspace_table_id: int,
    column_name: str,
) -> Optional[Dict[str, Any]]:
    rows = sql.execute_query_mappings(
        """
        SELECT
          wc.sample_values_json,
          wc.sample_stats_json,
          wc.sample_ran_at,
          wc.sample_error
        FROM workspace_column wc
        WHERE wc.workspace_table_id = :wtid
          AND wc.column_name = :col
          AND wc.exists_in_dbx = 1
        LIMIT 1
        """,
        {"wtid": int(workspace_table_id), "col": column_name},
    )
    return rows[0] if rows else None
