from __future__ import annotations

from app.services.domain.builder_feed.builder_table_feed_service import BuilderTableFeedService
from tests._support.fakes import FakeForgeQueryPort


def test_builder_table_feed_service_shapes_rows() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"workspace_table_id": 1, "table_label": "student"}]]
    service = BuilderTableFeedService(sql=sql)
    payload = service.list_domain_tables(workspace_id="ws", user_id="u1", domain_id=None)
    assert payload["rows"][0]["workspace_table_id"] == 1
    assert payload["rows"][0]["model_table_id"] == 1
