from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_result_rows


class DomainSummaryReadService:
    """
    Returns per-domain summary for the domains list screen:
      - table_count
      - table_sample: up to N table_name values (chips)
    """

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_domain_summaries(self, *, workspace_id: str, sample_size: int = 2) -> List[Dict[str, Any]]:
        sample_size = max(0, int(sample_size))

        # MySQL 8+ (window functions). If you're not on MySQL 8, tell me and I'll give the fallback query.
        sql = """
          WITH mapped AS (
            SELECT
              dwt.domain_id,
              wt.table_name,
              ROW_NUMBER() OVER (PARTITION BY dwt.domain_id ORDER BY wt.table_name) AS rn
            FROM domain_workspace_table dwt
            JOIN domain d
              ON d.id = dwt.domain_id
            AND d.workspace_id = :ws
            AND d.is_active = 1
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
            -- optional: only show/count tables that currently exist in dbx
            AND wt.exists_in_dbx = 1
          ),
          counts AS (
            SELECT domain_id, COUNT(*) AS table_count
            FROM mapped
            GROUP BY domain_id
          )
          SELECT
            d.id AS domain_id,
            COALESCE(c.table_count, 0) AS table_count,
            m.table_name AS sample_table_name
          FROM domain d
          LEFT JOIN counts c ON c.domain_id = d.id
          LEFT JOIN mapped  m ON m.domain_id = d.id AND m.rn <= :n
          WHERE d.workspace_id = :ws
            AND d.is_active = 1
          ORDER BY d.name, m.table_name
        """

        params: Dict[str, Any] = {"ws": workspace_id, "n": sample_size}

        rows = self._sql.execute_query_mappings(sql, params)

        # Rows look like:
        # {domain_id, table_count, sample_table_name}
        # We need:
        # {id, table_count, table_sample:[...]}
        by_id: Dict[int, Dict[str, Any]] = {}

        for r in rows:
            did = int(r["domain_id"])
            if did not in by_id:
                by_id[did] = {"id": did, "table_count": int(r["table_count"] or 0), "table_sample": []}
            tn = r.get("sample_table_name")
            if tn:
                by_id[did]["table_sample"].append(str(tn))

        # Ensure domains with zero mappings still appear even if query returns none (shouldn’t, but safe)
        result = list(by_id.values())
        return serialize_result_rows(result)
