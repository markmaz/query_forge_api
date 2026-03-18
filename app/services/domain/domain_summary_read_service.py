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

        # MySQL 8+ window functions. Includes QF-specific concept_count from semantic concept mappings.
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
             AND wt.exists_in_dbx = 1
          ),
          table_counts AS (
            SELECT domain_id, COUNT(*) AS table_count
            FROM mapped
            GROUP BY domain_id
          ),
          concept_counts AS (
            SELECT dsc.domain_id, COUNT(DISTINCT dsc.concept_id) AS concept_count
            FROM domain_semantic_concept dsc
            JOIN domain d ON d.id = dsc.domain_id AND d.workspace_id = :ws AND d.is_active = 1
            GROUP BY dsc.domain_id
          )
          SELECT
            d.id AS domain_id,
            COALESCE(tc.table_count, 0) AS table_count,
            COALESCE(cc.concept_count, 0) AS concept_count,
            m.table_name AS sample_table_name
          FROM domain d
          LEFT JOIN table_counts tc ON tc.domain_id = d.id
          LEFT JOIN concept_counts cc ON cc.domain_id = d.id
          LEFT JOIN mapped m ON m.domain_id = d.id AND m.rn <= :n
          WHERE d.workspace_id = :ws
            AND d.is_active = 1
          ORDER BY d.name, m.table_name
        """

        params: Dict[str, Any] = {"ws": workspace_id, "n": sample_size}

        rows = self._sql.execute_query_mappings(sql, params)

        # Collapse multi-row result (one per sample table) into domain-level dicts.
        # Shape: {id, table_count, concept_count, table_sample: [...]}
        by_id: Dict[int, Dict[str, Any]] = {}

        for r in rows:
            did = int(r["domain_id"])
            if did not in by_id:
                by_id[did] = {
                    "id": did,
                    "table_count": int(r["table_count"] or 0),
                    "concept_count": int(r["concept_count"] or 0),
                    "table_sample": [],
                }
            tn = r.get("sample_table_name")
            if tn:
                by_id[did]["table_sample"].append(str(tn))

        result = list(by_id.values())
        return serialize_result_rows(result)
