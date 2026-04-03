from __future__ import annotations

from typing import Any, Dict


def build_domain_summary_query(*, workspace_id: str, sample_size: int) -> tuple[str, Dict[str, Any]]:
    query = """
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
      ),
      table_counts AS (
        SELECT domain_id, COUNT(*) AS table_count
        FROM mapped
        GROUP BY domain_id
      )
      SELECT
        d.id AS domain_id,
        COALESCE(tc.table_count, 0) AS table_count,
        m.table_name AS sample_table_name
      FROM domain d
      LEFT JOIN table_counts tc ON tc.domain_id = d.id
      LEFT JOIN mapped m ON m.domain_id = d.id AND m.rn <= :n
      WHERE d.workspace_id = :ws
        AND d.is_active = 1
      ORDER BY d.name, m.table_name
    """
    params: Dict[str, Any] = {"ws": workspace_id, "n": sample_size}
    return query, params
