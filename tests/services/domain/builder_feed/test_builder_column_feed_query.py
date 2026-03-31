from __future__ import annotations

from datetime import datetime

from app.services.domain.builder_feed.builder_column_feed_query import (
    BuilderFeedQuery,
    build_builder_feed_params,
    build_builder_feed_sql,
    camelize_builder_row,
    qf_json_safe,
    qf_snake_to_camel,
)


def test_builder_feed_helpers() -> None:
    assert qf_snake_to_camel("workspace_table_id") == "workspaceTableId"
    assert qf_json_safe(datetime(2024, 1, 1)) == "2024-01-01T00:00:00"
    assert camelize_builder_row({"workspace_table_id": 1}) == {"workspaceTableId": 1}


def test_build_builder_feed_params() -> None:
    params = build_builder_feed_params(
        BuilderFeedQuery(workspace_id="ws", user_id="u1", domain_id=1, limit=5, offset=10, only_qe=True)
    )
    assert params["domain_id"] == 1
    assert params["only_qe"] == 1
    assert params["limit"] == 5
    assert params["offset"] == 10


def test_build_builder_feed_sql_show_all() -> None:
    sql_pack = build_builder_feed_sql("SHOW_ALL_QUALIFIED")
    assert "FROM base" in sql_pack.count_sql
    assert "qualified_name" in sql_pack.rows_sql
