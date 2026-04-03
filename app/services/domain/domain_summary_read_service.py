from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.summary.domain_summary_collapser import collapse_domain_summary_rows
from app.services.domain.summary.domain_summary_query_service import build_domain_summary_query


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
        query, params = build_domain_summary_query(workspace_id=workspace_id, sample_size=sample_size)
        rows = self._sql.execute_query_mappings(query, params)
        return collapse_domain_summary_rows(rows)
