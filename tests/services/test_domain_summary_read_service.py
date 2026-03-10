from __future__ import annotations

from app.services.domain.domain_summary_read_service import DomainSummaryReadService
from tests._support.fakes import FakeForgeQueryPort


def test_list_domain_summaries() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"domain_id": 1, "table_count": 2, "sample_table_name": "a"},
            {"domain_id": 1, "table_count": 2, "sample_table_name": "b"},
        ]
    ]
    service = DomainSummaryReadService(sql=sql)
    rows = service.list_domain_summaries(workspace_id="ws1", sample_size=2)
    assert rows[0]["table_count"] == 2
